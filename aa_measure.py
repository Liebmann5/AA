#!/usr/bin/env python3
"""aa_measure.py — take one measurement, write one file, zero typing.

Put this in the AA repo ROOT (next to packages/).

    python aa_measure.py                 # list the measurements
    python aa_measure.py gate            # writes measure_gate.txt
    python aa_measure.py static          # writes measure_static.txt
    python aa_measure.py math            # writes measure_math.txt
    python aa_measure.py suite           # writes measure_suite.txt
    python aa_measure.py all             # every one of them

Then attach the file it names:

    python kimicli.py --prompt p_gate.txt --request-code --attach measure_gate.txt

WHY THIS EXISTS
    Kimi cannot execute anything. Every "measure first" instruction has to be
    satisfied by you, on the real machine, before the prompt is sent. This
    script is that step, reduced to one word.

    It finds the venv interpreter itself, so `python aa_measure.py` works even
    from a bare shell -- the bare-`python` mistake that cost you an hour
    cannot happen here.

    Nothing here writes to the repo. It only reads and reports.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "packages" / "auto_apply"
SRC = PKG / "src" / "auto_apply"


# --------------------------------------------------------------------------
# Interpreter discovery — the whole point is that you cannot get this wrong
# --------------------------------------------------------------------------

def find_python() -> str:
    """Return the venv interpreter, or explain why we cannot."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",   # Windows
        ROOT / ".venv" / "bin" / "python3",          # POSIX
        ROOT / ".venv" / "bin" / "python",
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    print("!! No virtualenv found at .venv/ next to this script.")
    print("   Looked for:")
    for c in candidates:
        print("     ", c)
    print("\n   Create it with:  uv sync")
    print("   Falling back to the interpreter running this script, which may")
    print("   be missing mypy / pytest / hypothesis.\n")
    return sys.executable


PY = find_python()


# --------------------------------------------------------------------------
# Plumbing
# --------------------------------------------------------------------------

class Report:
    """Accumulates one measurement file."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.lines: list[str] = []
        self.t0 = time.time()
        self.head(f"AA MEASUREMENT — {name}")
        self.kv("taken", time.strftime("%Y-%m-%d %H:%M:%S"))
        self.kv("machine", f"{platform.system()} {platform.release()}")
        self.kv("interpreter", PY)
        self.kv("repo root", str(ROOT))

    def head(self, text: str) -> None:
        self.lines += ["", "=" * 78, text, "=" * 78]

    def sub(self, text: str) -> None:
        self.lines += ["", "-" * 78, text, "-" * 78]

    def kv(self, k: str, v: str) -> None:
        self.lines.append(f"{k:>14}: {v}")

    def note(self, text: str) -> None:
        self.lines += ["", text]

    def run(self, label: str, cmd: list[str], cwd: Path,
            tail: int | None = None, note: str = "") -> str:
        """Run a command, record everything, return its stdout+stderr."""
        self.sub(label)
        if note:
            self.lines += [f"# {note}", ""]
        self.lines.append("$ " + " ".join(
            f'"{c}"' if " " in c else c for c in cmd))
        self.lines.append(f"  (cwd: {cwd})")
        self.lines.append("")
        print(f"  ... {label}", flush=True)
        try:
            p = subprocess.run(cmd, cwd=str(cwd), capture_output=True,
                               encoding="utf-8", errors="replace", timeout=1800)
            out = (p.stdout or "") + (p.stderr or "")
            self.lines.append(f"[exit code: {p.returncode}]")
        except FileNotFoundError as e:
            out = f"COMMAND NOT FOUND: {e}"
            self.lines.append("[exit code: n/a — command not found]")
        except subprocess.TimeoutExpired:
            out = "TIMED OUT after 1800s"
            self.lines.append("[exit code: n/a — timeout]")
        self.lines.append("")
        body = out.splitlines()
        if tail is not None and len(body) > tail:
            self.lines.append(f"... {len(body) - tail} earlier line(s) omitted ...")
            # tail=0 means "record nothing" -- body[-0:] is the WHOLE list, so
            # this must be an explicit empty, not a negative slice.
            body = body[-tail:] if tail > 0 else []
        self.lines += body
        return out

    def grep(self, label: str, pattern: str, where: Path,
             note: str = "", max_hits: int = 200) -> None:
        """Record every line in `where` matching `pattern`, with file:line."""
        import re
        self.sub(label)
        if note:
            self.lines += [f"# {note}", ""]
        self.lines.append(f"# pattern: {pattern}")
        self.lines.append(f"# under:   {where.relative_to(ROOT)}")
        self.lines.append("")
        rx = re.compile(pattern)
        hits = 0
        for p in sorted(where.rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            try:
                for n, line in enumerate(
                        p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if rx.search(line):
                        hits += 1
                        if hits <= max_hits:
                            rel = p.relative_to(ROOT).as_posix()
                            self.lines.append(f"{rel}:{n}: {line.strip()}")
            except Exception as e:
                self.lines.append(f"[unreadable: {p} — {e}]")
        if hits > max_hits:
            self.lines.append(f"... and {hits - max_hits} more (capped)")
        self.lines.append("")
        self.lines.append(f"[{hits} hit(s)]")

    def show(self, label: str, path: Path, start: int = 1, count: int | None = None,
             note: str = "") -> None:
        """Record a numbered slice of a file. count=None means THE WHOLE FILE.

        Default to the whole file. A truncated attachment is worse than a
        large one: a model asked to emit a complete file it has only seen
        half of must either refuse or invent the rest, and both cost a
        round trip. This defaulted to 75 lines once and cost exactly that.
        """
        self.sub(label)
        if note:
            self.lines += [f"# {note}", ""]
        if not path.is_file():
            self.lines.append(f"!! FILE NOT FOUND: {path}")
            return
        span = ("COMPLETE FILE, all "
                f"{len(path.read_text(encoding='utf-8', errors='replace').splitlines())} lines"
                if count is None else f"lines {start}-{start + count - 1}")
        self.lines.append(f"# {path.relative_to(ROOT).as_posix()} — {span}")
        self.lines.append("")
        all_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        end = len(all_lines) if count is None else min(start - 1 + count, len(all_lines))
        for i in range(start - 1, end):
            self.lines.append(f"{i + 1:5}| {all_lines[i]}")

    def save(self) -> Path:
        out = ROOT / f"measure_{self.name}.txt"
        self.head("END OF MEASUREMENT")
        self.kv("elapsed", f"{time.time() - self.t0:.1f}s")
        out.write_text("\n".join(self.lines) + "\n", encoding="utf-8")
        return out


# --------------------------------------------------------------------------
# The measurements
# --------------------------------------------------------------------------

def m_gate() -> Report:
    """Everything Kimi needs to fix the mypy gate's invocation."""
    r = Report("gate")
    r.note(
        "PURPOSE: the gate runs mypy with --explicit-package-bases, which names\n"
        "modules 'src.auto_apply.*' while the code imports 'auto_apply.*'. If\n"
        "that is what is happening, every internal cross-module import resolves\n"
        "to Any and the gate has been checking almost nothing.\n"
        "The three runs below settle it."
    )
    r.run("A: WITH --explicit-package-bases (what the gate runs)",
          [PY, "-m", "mypy", "--config-file", "../../pyproject.toml",
           "--explicit-package-bases", "src/auto_apply"],
          cwd=PKG, tail=40)
    r.run("B: WITHOUT it (what the gate's docstring says to run)",
          [PY, "-m", "mypy", "--config-file", "../../pyproject.toml",
           "src/auto_apply"],
          cwd=PKG)
    out = r.run("C: module naming under the gate's invocation",
                [PY, "-m", "mypy", "--config-file", "../../pyproject.toml",
                 "--explicit-package-bases", "src/auto_apply", "--verbose"],
                cwd=PKG, tail=0,
                note="only the BuildSource lines are kept, below")
    r.sub("C (filtered): the first BuildSource lines")
    kept = [ln for ln in out.splitlines() if "BuildSource" in ln][:5]
    r.lines += kept or ["!! no BuildSource lines found — mypy may have failed above"]
    r.show("The gate itself — COMPLETE, so it can be emitted back in full",
           PKG / "tests" / "infrastructure" / "test_mypy_gate.py",
           note="this is the file to be corrected")
    r.run("Does the tests/ tree survive WITHOUT the flag?",
          [PY, "-m", "mypy", "--config-file", "../../pyproject.toml", "tests"],
          cwd=PKG, tail=12,
          note="if this reports a duplicate conftest module, the flag is "
               "REQUIRED for tests/ and the two gates need different "
               "invocations — do not drop it for both")
    return r


def m_static() -> Report:
    """Everything Kimi needs for the zero-browser static path."""
    r = Report("static")
    r.note(
        "PURPOSE: on a real 2-core laptop the static fallback was built,\n"
        "announced as STATIC_ASSISTED, and then every task raised\n"
        "RuntimeError at orchestrator.py:1106. Also providers=0.\n"
        "This gathers the code that decides both."
    )
    r.show("orchestrator.run() — where the raise is triggered",
           SRC / "application" / "agent" / "orchestrator.py", 360, 32)
    r.show("_ensure_browser_active — the raise itself",
           SRC / "application" / "agent" / "orchestrator.py", 1090, 30)
    r.grep("Every requires_live_browser site", r"requires_live_browser", SRC,
           note="does ANY provider declare False?")
    r.grep("Provider registration in the composition root",
           r"provider|Provider", SRC / "infrastructure", max_hits=80)
    r.grep("Static / BS4 wiring",
           r"STATIC_ASSISTED|BS4Perception|static", SRC / "infrastructure")
    r.grep("The cascade's failure reporting",
           r"ALL BROWSERS FAILED|FAILED\]|exhausted|static candidate",
           SRC / "infrastructure")
    r.grep("Low-resource threshold",
           r"low_resource|is_low_resource|LOW_RESOURCE", SRC,
           note="did NOT fire on 2 cores / 3787 MB RAM / 2015 MB free disk")
    return r


def m_math() -> Report:
    """Everything Kimi needs to wire the deterministic math services."""
    r = Report("math")
    r.note(
        "PURPOSE: honeypot_detection.py has zero importers. entropy.py and\n"
        "occlusion.py are imported ONLY by it, so all three are dead as a\n"
        "chain. transformations.py is separately dead. Wiring one module\n"
        "revives three."
    )
    for mod in ("entropy", "occlusion", "honeypot_detection", "transformations"):
        r.grep(f"Importers of domain.services.{mod}",
               rf"services\.{mod}\b|services import .*\b{mod}\b|\bfrom .*{mod} import",
               SRC, note="excluding the module's own file, below")
    r.show("honeypot_detection.py — the public entry point",
           SRC / "domain" / "services" / "honeypot_detection.py", 170, 30)
    r.grep("Where honeypots are currently handled INLINE (the duplicate)",
           r"honeypot|Honeypot", SRC,
           note="a second implementation would be a DRY violation")
    r.grep("The live occlusion check (the OTHER implementation)",
           r"occlu|Occlu|getBoundingClientRect|elementFromPoint", SRC)
    r.grep("Form field classification — the natural consumer",
           r"class FormUnderstanding|def analyze_form|classify_field|FieldType",
           SRC, max_hits=60)
    return r


def m_suite() -> Report:
    """The full verification loop. Run after every apply."""
    r = Report("suite")
    r.note("BASELINE: 1093 passed, 0 failed. Anything less is a regression.")
    r.run("Full test suite", [PY, "-m", "pytest", "tests", "-q"],
          cwd=PKG, tail=60)
    r.run("Type gate (gate's own invocation)",
          [PY, "-m", "mypy", "--config-file", "../../pyproject.toml",
           "--explicit-package-bases", "src/auto_apply"], cwd=PKG, tail=15)
    r.run("Type gate (corrected invocation)",
          [PY, "-m", "mypy", "--config-file", "../../pyproject.toml",
           "src/auto_apply"], cwd=PKG, tail=15)
    r.run("Undefined names", [PY, "-m", "ruff", "check", "--select", "F821", "src/"],
          cwd=PKG, tail=20)
    r.run("Everything still compiles",
          [PY, "-c",
           "import compileall,sys; sys.exit(0 if compileall.compile_dir('src', quiet=1) else 1)"],
          cwd=PKG, tail=20,
          note="compiles only — compileall never imports, so it CANNOT catch "
               "a module that fails to import (it caught none of the four "
               "broken modules deleted 2026-08-30). That check lives in "
               "tests/architecture/test_module_reachability.py"
               "::test_src_modules_are_importable.")
    return r


def m_pins() -> Report:
    """After the two structural pins land — capture their first real run."""
    r = Report("pins")
    r.note(
        "PURPOSE: the pins ship with EMPTY exemption dicts so run one prints\n"
        "the executed truth. This captures it. Kimi predicted 21 flagged ports\n"
        "and 53 unreachable modules from a manual trace; this is the real\n"
        "number, and it supersedes the prediction."
    )
    r.run("The structural pins, verbose",
          [PY, "-m", "pytest", "tests/architecture", "-q", "-rA", "--tb=long"],
          cwd=PKG)
    return r


MEASUREMENTS = {
    "gate":   ("fix the mypy gate invocation",        m_gate),
    "static": ("the zero-browser static path",        m_static),
    "math":   ("wire the deterministic math services", m_math),
    "pins":   ("capture the structural pins' first run", m_pins),
    "suite":  ("full verification — run after every apply", m_suite),
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if not PKG.is_dir():
        print(f"!! packages/auto_apply not found under {ROOT}")
        print("   Put aa_measure.py in the AA repo root, next to packages/.")
        return 2

    if not args:
        print(__doc__.split("WHY THIS EXISTS")[0])
        print("Available measurements:\n")
        for k, (desc, _) in MEASUREMENTS.items():
            print(f"    {k:<8} {desc}")
        print(f"\n    {'all':<8} run every one")
        print(f"\nInterpreter that will be used:\n    {PY}\n")
        return 0

    wanted = list(MEASUREMENTS) if args[0] == "all" else args
    written: list[Path] = []
    for name in wanted:
        if name not in MEASUREMENTS:
            print(f"!! unknown measurement: {name}")
            print(f"   choose from: {', '.join(MEASUREMENTS)}, all")
            return 2
        desc, fn = MEASUREMENTS[name]
        print(f"\n== {name}: {desc}")
        report = fn()
        path = report.save()
        written.append(path)
        print(f"   -> {path.name}")

    print("\nDone. Attach with:\n")
    attach = " ".join(f"--attach {p.name}" for p in written)
    print(f"    python kimicli.py --prompt <prompt>.txt --request-code {attach}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
