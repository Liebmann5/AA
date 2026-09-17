#!/usr/bin/env python3
"""retire.py — move a file into docs/old_retired_files/ instead of deleting it.

Usage, from the repository root:

    python retire.py <path-to-file> "<one-line reason>"
    python retire.py <path-to-file> "<reason>" --dry-run
    python retire.py --recall packages/auto_apply/docs/old_retired_files/<...>

What it does:
  1. git mv (plain move outside git) into
     packages/auto_apply/docs/old_retired_files/<original relative path>
  2. shifts the file down one line and writes the original path into line 1
     as a comment in that file's own comment syntax
  3. prints the ledger row to paste into that directory's README.md

Never touches build artefacts: __pycache__, .venv, *.pyc and friends are
deleted normally and are refused here.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import shutil
import subprocess
import sys
from pathlib import Path

RETIRED_ROOT = Path("packages/auto_apply/docs/old_retired_files")

# extension -> (prefix, suffix). suffix is "" for line comments.
COMMENT_SYNTAX: dict[str, tuple[str, str]] = {
    ".py": ("# ", ""),
    ".pyi": ("# ", ""),
    ".yaml": ("# ", ""),
    ".yml": ("# ", ""),
    ".toml": ("# ", ""),
    ".cfg": ("# ", ""),
    ".ini": ("; ", ""),
    ".ps1": ("# ", ""),
    ".sh": ("# ", ""),
    ".rb": ("# ", ""),
    ".js": ("// ", ""),
    ".ts": ("// ", ""),
    ".jsx": ("// ", ""),
    ".tsx": ("// ", ""),
    ".java": ("// ", ""),
    ".c": ("// ", ""),
    ".h": ("// ", ""),
    ".cpp": ("// ", ""),
    ".rs": ("// ", ""),
    ".go": ("// ", ""),
    ".sql": ("-- ", ""),
    ".md": ("<!-- ", " -->"),
    ".html": ("<!-- ", " -->"),
    ".htm": ("<!-- ", " -->"),
    ".xml": ("<!-- ", " -->"),
    ".css": ("/* ", " */"),
}

# Regenerable machine output. The policy protects authored work, not this.
REFUSED_PARTS = {
    "__pycache__", ".venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".kimi_out", ".git", "node_modules", "htmlcov", ".tox",
}
REFUSED_SUFFIXES = {".pyc", ".pyo", ".log", ".coverage"}

# Personal data must never enter the retirement directory: everything there is
# committed and shipped to every person who clones AA. These are backstops --
# the real check is reading the file before you retire it.
PERSONAL_DATA_PARTS = {"dev_data", "screenshots", "logs", "profiles", "resumes", "documents"}
PERSONAL_DATA_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".png", ".jpg", ".jpeg",
                          ".pdf", ".docx", ".env", ".pem", ".key"}
PERSONAL_DATA_NAMES = {".env", "cookies.json", "session.json"}


def _fail(message: str) -> None:
    print(f"retire: {message}", file=sys.stderr)
    raise SystemExit(1)


def _in_git() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            check=True, capture_output=True,
        )
        return True
    except (OSError, subprocess.CalledProcessError):
        return False


def _move(src: Path, dest: Path, use_git: bool) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if use_git:
        result = subprocess.run(
            ["git", "mv", str(src), str(dest)], capture_output=True, text=True
        )
        if result.returncode == 0:
            return "git mv (history preserved)"
        print(f"retire: git mv declined ({result.stderr.strip()}); using a plain move")
    shutil.move(str(src), str(dest))
    return "plain move"


def _stamp(dest: Path, original: str) -> str:
    """Shift the file down one line; line 1 becomes the original path."""
    syntax = COMMENT_SYNTAX.get(dest.suffix.lower())
    if syntax is None:
        return f"no comment syntax for '{dest.suffix}' — moved unchanged, origin recorded in the ledger only"

    prefix, suffix = syntax
    raw = dest.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "not UTF-8 text — moved unchanged, origin recorded in the ledger only"

    newline = "\r\n" if "\r\n" in text else "\n"
    stamp = f"{prefix}RETIRED FROM: {original}{suffix}"

    # A shebang must stay on line 1 or the file stops being executable.
    if text.startswith("#!"):
        first, sep, rest = text.partition(newline)
        body = first + sep + stamp + newline + rest
        note = "stamped on line 2 (line 1 is a shebang)"
    else:
        body = stamp + newline + text
        note = "stamped on line 1"

    dest.write_text(body, encoding="utf-8", newline="")
    return note


def _line_count(path: Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def retire(target: str, reason: str, dry_run: bool) -> None:
    src = Path(target.replace("\\", "/"))
    if not src.is_file():
        _fail(f"'{src}' is not a file")
    if set(src.parts) & REFUSED_PARTS or src.suffix.lower() in REFUSED_SUFFIXES:
        _fail(
            f"'{src}' is regenerable machine output. The no-delete policy covers "
            "authored work only — delete this normally."
        )
    if (set(src.parts) & PERSONAL_DATA_PARTS
            or src.suffix.lower() in PERSONAL_DATA_SUFFIXES
            or src.name.lower() in PERSONAL_DATA_NAMES):
        _fail(
            f"'{src}' looks like personal data or a credential. The retirement "
            "directory is committed and shipped to everyone who clones AA, so "
            "nothing about a person goes in it. Retire the code, not the data."
        )

    original = src.as_posix()
    dest = RETIRED_ROOT / src

    if dest.exists():
        _fail(
            f"'{dest.as_posix()}' already exists. That file has been retired before — "
            "check the ledger; you may be about to lose the earlier copy."
        )

    lines = _line_count(src)
    if dry_run:
        print("DRY RUN — nothing written")
        print(f"  from : {original}")
        print(f"  to   : {dest.as_posix()}")
        print(f"  stamp: {COMMENT_SYNTAX.get(src.suffix.lower(), ('<none>', ''))[0]}RETIRED FROM: {original}")
        return

    how = _move(src, dest, _in_git())
    note = _stamp(dest, original)

    today = _dt.date.today().isoformat()
    print(f"retired: {original}")
    print(f"      -> {dest.as_posix()}   [{how}; {note}]")
    print()
    print("Paste this into packages/auto_apply/docs/old_retired_files/README.md,")
    print("under RETIRED, and fill the last two columns before you commit:")
    print()
    print(
        f"| {today} | `{src.name}` | `{original}` | {reason} | "
        f"_{lines} lines — what it does, and how complete it is_ | _AS-IS / AFTER-REWIRE / IDEA-ONLY / SUPERSEDED-BY_ |"
    )


def recall(target: str, dry_run: bool) -> None:
    src = Path(target.replace("\\", "/"))
    if not src.is_file():
        _fail(f"'{src}' is not a file")
    try:
        rel = src.relative_to(RETIRED_ROOT)
    except ValueError:
        _fail(f"'{src}' is not inside {RETIRED_ROOT.as_posix()}")

    first = src.read_text(encoding="utf-8", errors="replace").splitlines()[:1]
    if not first or "RETIRED FROM:" not in first[0]:
        print("retire: warning — line 1 carries no origin stamp; using the directory layout instead")
        dest = rel
    else:
        dest = Path(first[0].split("RETIRED FROM:", 1)[1].strip(" -->*/").strip())

    if dry_run:
        print("DRY RUN — nothing written")
        print(f"  from : {src.as_posix()}")
        print(f"  to   : {dest.as_posix()}")
        return
    if dest.exists():
        _fail(f"'{dest.as_posix()}' already exists — resolve by hand")

    how = _move(src, dest, _in_git())
    text = dest.read_text(encoding="utf-8")
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.split(newline)
    if lines and "RETIRED FROM:" in lines[0]:
        dest.write_text(newline.join(lines[1:]), encoding="utf-8", newline="")
    print(f"recalled: {src.as_posix()}")
    print(f"       -> {dest.as_posix()}   [{how}; origin stamp removed]")
    print()
    print("Move the ledger row from RETIRED to RECALLED and say what changed the verdict.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Retire a file instead of deleting it.",
    )
    parser.add_argument("path", help="file to retire, or to recall with --recall")
    parser.add_argument("reason", nargs="?", default="", help="one-line reason (required unless --recall)")
    parser.add_argument("--recall", action="store_true", help="move a retired file back to its original path")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, write nothing")
    args = parser.parse_args()

    if args.recall:
        recall(args.path, args.dry_run)
        return
    if not args.reason:
        _fail("a one-line reason is required. An unexplained retirement is a deletion with extra steps.")
    retire(args.path, args.reason, args.dry_run)


if __name__ == "__main__":
    main()
