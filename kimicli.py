#!/usr/bin/env python3
r"""
kimicli.py - Kimi K3 workbench (v3)

Design rules, in priority order:

  1. YOUR CODEBASE IS NEVER TOUCHED BY THE MODEL.
     Kimi has no tools and no filesystem access. Every change it proposes is
     staged under .kimi_out/<session>/proposed/ ONLY. Nothing reaches the repo
     until you run --apply-fixes yourself.

  2. SMALL, EXACT EDITS - NOT WHOLE FILES.
     Kimi sends '### EDIT:' search/replace blocks for existing files (the same
     old/new string-replacement semantics as Kimi's own StrReplaceFile tool),
     and '### FILE:' only for new files. An edit applies only where its SEARCH
     text occurs EXACTLY ONCE in the file as it is on disk NOW; anything else
     rejects the whole batch. Line endings, BOM and every untouched byte are
     preserved exactly.

  3. ALL OR NOTHING, VERIFIED, UNDOABLE.
     Pass 1 resolves every block against the live tree and runs the checks
     (syntax, undefined names, cross-file imports, paths). Pass 2 backs up and
     VERIFIES every original, writes the manifest BEFORE touching the repo,
     writes each file atomically and verifies it, and rolls everything back
     automatically if any write fails. --undo restores byte-for-byte, is
     all-or-nothing, can be re-run safely, and never destroys anything.

  4. NOTHING IS DROPPED SILENTLY.
     Every block-shaped thing in a reply is either parsed or reported, with its
     reply line number. A cut-off reply is detected. A failure produces a
     ready-made repair prompt for a cheap cached --resume.

  5. NOTHING IS LOST TO THE TERMINAL; NO SURPRISE BILLS.
     Every token is appended to transcript.md as it arrives; each turn's reply
     is also saved on its own. Streaming, no SDK auto-retries, a preflight that
     prints the cost before sending, a spend cap, and a running ledger.

Verified against the Kimi platform docs on 2026-08-05:
  - context caching is automatic; prefix must be byte-identical  -> codebase first
  - usage.cached_tokens is TOP-LEVEL in usage (not prompt_tokens_details)
  - prompt_cache_key improves hit rate across separate invocations
  - 504 after 900s on long non-streaming requests            -> stream=True always
  - reasoning_effort is top-level: low | high | max (default max)
  - temperature/top_p/n/penalties are FIXED on K3            -> never sent
  - max_completion_tokens (max_tokens is deprecated)
  - K3 uses Preserved Thinking -> keep reasoning_content in history

Quick start:
    python kimicli.py --selftest                      # prove apply/undo on THIS machine
    python kimicli.py --prompt task.md --request-code
    python kimicli.py --apply-fixes last --dry-run
    python kimicli.py --apply-fixes last
    python kimicli.py --undo last
    python kimicli.py --history
"""

from __future__ import annotations

import argparse
import ast
import bisect
import contextlib
import difflib
import fnmatch
import hashlib
import io
import json
import logging
import os
import re
import shutil
import subprocess
import symtable
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------
# Console: make Windows cp1252 consoles stop killing the run on a stray glyph.
# (Same root fix as AA's apply_unicode_safe_logging.)
for _stream_name in ("stdout", "stderr"):
    _stream = getattr(sys, _stream_name, None)
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
    except Exception:
        pass

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv is optional
    def load_dotenv(*_a: Any, **_k: Any) -> bool:  # type: ignore[misc]
        return False

# ==========================================================================
# Configuration
# ==========================================================================

PROJECT_ROOT = Path(os.getenv("KIMI_PROJECT_ROOT", Path(__file__).parent)).resolve()

load_dotenv()
_alt_env = PROJECT_ROOT / "packages" / "auto_apply" / ".env"
if _alt_env.exists():
    load_dotenv(dotenv_path=_alt_env, override=True)

API_KEY = os.getenv("MOONSHOT_API_KEY") or os.getenv("KIMI_API_KEY") or ""
BASE_URL = os.getenv("KIMI_BASE_URL", "https://api.moonshot.ai/v1")
MODEL = os.getenv("KIMI_MODEL", "kimi-k3")

DEFAULT_CODEBASE = Path(os.getenv("KIMI_CODEBASE", r"D:\Downloads\AA-kimi.txt"))

OUT_DIR = PROJECT_ROOT / ".kimi_out"          # sessions, transcripts, staged files
BACKUP_DIR = PROJECT_ROOT / ".kimi_backups"   # backups + manifests
LEDGER = OUT_DIR / "ledger.jsonl"

# Kimi K3 pricing, USD per 1M tokens (docs/pricing/chat-k3)
PRICE_IN_CACHED = 0.30
PRICE_IN_FRESH = 3.00
PRICE_OUT = 15.00

CONTEXT_WINDOW = 1_048_576
# Your organisation's tokens-per-minute ceiling, from
# platform.kimi.ai/console/limits. Override with KIMI_TPM in .env when the
# tier changes. The preflight warns only when a request exceeds THIS, not a
# hardcoded guess at someone else's tier.
ACCOUNT_TPM = int(os.getenv("KIMI_TPM", "3000000"))
DEFAULT_MAX_COMPLETION = 131_072      # K3's own default
REQUEST_TIMEOUT_S = float(os.getenv("KIMI_TIMEOUT", "2400"))

# Files the model is never allowed to touch, even with --apply-fixes.
PROTECTED = (
    ".git", ".venv", "venv", "node_modules", ".kimi_out", ".kimi_backups",
    ".ds_backups", "__pycache__", ".env", "kimicli.py", "callapi.py",
    # Retired work is never overwritten by the model: the whole point of
    # docs/old_retired_files/ is that what lands there cannot be lost.
    "old_retired_files", "retire.py",
    # Personal data. dev_data/ holds the profile database, screenshots and
    # logs; none of it is source and none of it is the model's to rewrite.
    "dev_data",
)

MANIFEST_VERSION = 3                  # .kimi_backups/manifest_<id>.json format


logger = logging.getLogger("kimi")


def setup_logging(logfile: Optional[Path] = None, verbose: bool = False) -> None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    con = logging.StreamHandler(sys.stdout)
    con.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
    logger.addHandler(con)
    if logfile:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)


# ==========================================================================
# Small utilities
# ==========================================================================

def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


#: Chars per token, measured against the tokenizer on this repository:
#:     item 2   est 55,533 (@3.6)   exact 40,521   ->  4.93
#:     item 4a  est 69,665 (@3.6)   exact 51,621   ->  4.86
#: The old 3.6 was chosen to err high and did, by about a third, on every
#: per-attachment line of the preflight table that a send decision is made
#: from. Re-measure and update this if the ratio drifts; the preflight prints
#: estimate-vs-exact on every call precisely so the drift stays visible.
EST_CHARS_PER_TOKEN = 4.9

#: The estimate also backs the context-window guard when --no-count is set,
#: and a LOW reading is the dangerous one there: the request fails after the
#: dump has been built and sent. A calibrated estimator is as likely to sit
#: under the truth as over it, so the guard applies this margin explicitly
#: rather than depending on the estimator being quietly pessimistic.
EST_WINDOW_SAFETY = 1.35


def est_tokens(text: str) -> int:
    """Local estimate, calibrated (see EST_CHARS_PER_TOKEN).

    Used for the cost table and the spend guard. The context-window check
    scales this by EST_WINDOW_SAFETY when no exact count is available.
    """
    return int(len(text) / EST_CHARS_PER_TOKEN) if text else 0


def money(x: float) -> str:
    return f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def cost_of(prompt: int, cached: int, completion: int) -> float:
    fresh = max(prompt - cached, 0)
    return (cached * PRICE_IN_CACHED + fresh * PRICE_IN_FRESH + completion * PRICE_OUT) / 1e6


def _attach_label(p: Path) -> str:
    """The name an attachment is announced under: its repo-relative path.

    The attachment name is the ONLY place the model learns where a file lives.
    Announcing the bare basename means a model asked to emit
    ``### EDIT: <full path>`` blocks has to guess each directory. On item 4a it
    guessed ``tests/pins/`` for a file in ``tests/architecture/`` and the whole
    batch was correctly rejected — six good files thrown away over a path the
    model was never told. Falls back to the basename for a file outside the
    project root, where no relative path exists.
    """
    try:
        return p.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (ValueError, OSError):
        return p.name


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")



def atomic_write(path: Path, content: str, newline: str = "\n") -> None:
    """Write via a temp file in the same directory, fsync, then replace. A crash
    mid-write can never leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = content.replace("\n", newline) if newline != "\n" else content
    write_bytes_atomic(path, data.encode("utf-8"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def confirm(question: str, default_no: bool = True) -> bool:
    suffix = " [y/N] " if default_no else " [Y/n] "
    try:
        ans = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if not ans:
        return not default_no
    return ans in ("y", "yes")


# ==========================================================================
# Repo dump: load, optionally filter out directories you don't want to pay for
# ==========================================================================

# repo2txt-style section headers. Tolerant: if none match we leave the dump
# alone rather than mangling it silently.
SECTION_PATTERNS = [
    re.compile(r"(?m)^-{3,}\s*\nFile:\s*(?P<path>.+?)\s*\n-{3,}\s*$"),
    re.compile(r"(?m)^={3,}\s*\nFILE:\s*(?P<path>.+?)\s*\n={3,}\s*$"),
    re.compile(r"(?m)^#{1,3}\s*File:\s*(?P<path>.+?)\s*$"),
    re.compile(r"(?m)^/{2,}\s*File:\s*(?P<path>.+?)\s*$"),
]


def split_dump(dump: str) -> Tuple[List[Tuple[str, str]], str]:
    """Return ([(path, section_text_including_header)], pattern_name).
    Empty list means: format not recognised, do not filter."""
    best: List[Any] = []
    best_pat = ""
    for pat in SECTION_PATTERNS:
        hits = list(pat.finditer(dump))
        if len(hits) > len(best):
            best, best_pat = hits, pat.pattern[:24]
    if len(best) < 2:            # one match is more likely a coincidence than a format
        return [], ""
    out: List[Tuple[str, str]] = []
    for i, m in enumerate(best):
        end = best[i + 1].start() if i + 1 < len(best) else len(dump)
        out.append((m.group("path").strip(), dump[m.start():end]))
    return out, best_pat


def filter_dump(dump: str, excludes: Sequence[str]) -> Tuple[str, str]:
    """Drop sections whose path matches any exclude prefix/substring.
    Returns (new_dump, human_report)."""
    if not excludes:
        return dump, ""
    sections, _ = split_dump(dump)
    if not sections:
        return dump, ("  !  codebase filter skipped: could not recognise the dump's file\n"
                      "     headers, so nothing was removed (the dump is sent unchanged).")
    kept, dropped, dropped_chars = [], 0, 0
    for path, body in sections:
        norm = path.replace("\\", "/").lstrip("./")
        if any(ex.replace("\\", "/").strip("/") in norm for ex in excludes):
            dropped += 1
            dropped_chars += len(body)
            continue
        kept.append(body)
    preamble = dump[:dump.find(sections[0][1])] if sections else ""
    new_dump = preamble + "".join(kept)
    report = (f"  -  filtered out {dropped} of {len(sections)} files "
              f"(~{est_tokens('x' * dropped_chars):,} tokens, "
              f"~{money(est_tokens('x' * dropped_chars) / 1e6 * PRICE_IN_FRESH)} per uncached call)\n"
              f"     keep the same --exclude flags every run: changing them changes the "
              f"prefix, which costs you the cache once.")
    return new_dump, report



# ==========================================================================
# Session store: transcript, message history, staged files, ledger
# ==========================================================================

@dataclass
class Usage:
    prompt: int = 0
    cached: int = 0
    completion: int = 0
    calls: int = 0

    def add(self, u: Dict[str, Any]) -> None:
        self.prompt += int(u.get("prompt_tokens") or 0)
        self.completion += int(u.get("completion_tokens") or 0)
        # Kimi returns cached_tokens at the top level of usage. Older/other
        # gateways nest it; accept both so the number is never silently zero.
        cached = u.get("cached_tokens")
        if cached is None:
            cached = (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        self.cached += int(cached or 0)
        self.calls += 1

    @property
    def cost(self) -> float:
        return cost_of(self.prompt, self.cached, self.completion)


class Session:
    """One conversation. Everything about it lives in .kimi_out/<id>/."""

    def __init__(self, session_id: Optional[str] = None):
        self.id = session_id or f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        self.dir = OUT_DIR / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "proposed").mkdir(exist_ok=True)
        self.transcript = self.dir / "transcript.md"
        self.thinking = self.dir / "thinking.md"
        self.messages_path = self.dir / "messages.json"
        self.usage = Usage()
        self.turn = 0
        self.messages: List[Dict[str, Any]] = []
        # The cache key this session was opened with. Persisted so that
        # --resume sends the SAME key as turn 1: a different key is a
        # different cache bucket, and the prefix you already paid for misses.
        self.cache_key: Optional[str] = None
        self.printed_stage_summary = False
        self._load()

    # -- persistence -------------------------------------------------
    def _load(self) -> None:
        if self.messages_path.exists():
            try:
                blob = json.loads(read_text(self.messages_path))
                self.messages = blob["messages"]
                self.turn = blob.get("turn", 0)
                self.cache_key = blob.get("cache_key")
                u = blob.get("usage", {})
                self.usage = Usage(**{k: u.get(k, 0) for k in ("prompt", "cached", "completion", "calls")})
            except Exception as exc:
                logger.warning("could not reload session state: %s", exc)

    def save(self) -> None:
        blob = {
            "session": self.id,
            "turn": self.turn,
            "cache_key": self.cache_key,
            "usage": self.usage.__dict__,
            "messages": self.messages,
        }
        atomic_write(self.messages_path, json.dumps(blob, indent=1, ensure_ascii=False))

    # -- transcript --------------------------------------------------
    def banner(self, kind: str, extra: str = "") -> None:
        line = f"\n\n{'=' * 78}\n== TURN {self.turn} - {kind}{(' - ' + extra) if extra else ''}\n{'=' * 78}\n\n"
        self._append(self.transcript, line)

    def write(self, text: str, to_thinking: bool = False) -> None:
        self._append(self.thinking if to_thinking else self.transcript, text)

    @staticmethod
    def _append(path: Path, text: str) -> None:
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()

    def save_reply(self, turn: int, text: str) -> Path:
        """Each turn's answer on its own, so reply line numbers mean something
        and --apply-fixes <file> can re-read it."""
        p = self.dir / f"reply_turn{turn}.md"
        atomic_write(p, text)
        return p

    # -- staged changes ------------------------------------------------
    @staticmethod
    def _safe_rel(rel_path: str) -> str:
        cleaned = re.sub(r"[^A-Za-z0-9._/\\-]", "_", rel_path).replace("\\", "/")
        # Drop '..' and drive letters: staging must never escape the session dir.
        parts = [seg for seg in cleaned.split("/") if seg not in ("", ".", "..") and ":" not in seg]
        return "/".join(parts) or "unnamed"

    def stage(self, rel_path: str, content: str, turn: int) -> Path:
        dest = self.dir / "proposed" / f"turn{turn}" / self._safe_rel(rel_path)
        atomic_write(dest, content)
        return dest

    def stage_edits(self, rel_path: str, edits: List["EditBlock"], turn: int) -> Path:
        dest = self.dir / "proposed" / f"turn{turn}" / (self._safe_rel(rel_path) + ".edits.json")
        atomic_write(dest, json.dumps({"path": rel_path, "edits": [e.to_json() for e in edits]},
                                      indent=1, ensure_ascii=False))
        return dest

    def rows(self) -> List[Dict[str, Any]]:
        index = self.dir / "proposals.json"
        if not index.exists():
            return []
        try:
            return json.loads(read_text(index))
        except ValueError:
            logger.warning("proposals.json is damaged in %s", self.dir)
            return []

    def append_rows(self, rows: List[Dict[str, Any]]) -> None:
        atomic_write(self.dir / "proposals.json", json.dumps(self.rows() + rows, indent=1))

    def read_artifact(self, row: Dict[str, Any]) -> Any:
        """FILE row -> text; EDIT row -> List[EditBlock]; None if missing."""
        p = self.dir / row["staged"]
        if not p.exists():
            return None
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            return None
        if row.get("kind", "file") == "edit":
            try:
                return [EditBlock.from_json(d) for d in json.loads(text)["edits"]]
            except (ValueError, KeyError, TypeError):
                return None
        return text

    def write_parse_report(self, turn: int, report: Dict[str, Any]) -> None:
        atomic_write(self.dir / f"parse_turn{turn}.json", json.dumps(report, indent=1))

    def parse_report(self, turn: int) -> Optional[Dict[str, Any]]:
        p = self.dir / f"parse_turn{turn}.json"
        if not p.exists():
            return None
        try:
            return json.loads(read_text(p))
        except ValueError:
            return None

    def turns_with_reports(self) -> List[int]:
        out = []
        for p in self.dir.glob("parse_turn*.json"):
            m = re.match(r"parse_turn(\d+)\.json$", p.name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def ledger_entry(self, u: Dict[str, Any], effort: str, note: str = "") -> None:
        cached = u.get("cached_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        row = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "session": self.id,
            "turn": self.turn,
            "effort": effort,
            "prompt": u.get("prompt_tokens", 0),
            "cached": cached,
            "completion": u.get("completion_tokens", 0),
            "cost_usd": round(cost_of(u.get("prompt_tokens", 0), cached, u.get("completion_tokens", 0)), 5),
            "note": note,
        }
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with open(LEDGER, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")


def resolve_session(token: str) -> Optional[Session]:
    """'last' -> newest session; otherwise an explicit id."""
    if token == "last":
        if not OUT_DIR.exists():
            return None
        dirs = sorted((d for d in OUT_DIR.iterdir() if d.is_dir()), key=lambda d: d.name)
        return Session(dirs[-1].name) if dirs else None
    if not re.match(r"^[A-Za-z0-9_.-]+$", token):
        return None
    return Session(token) if (OUT_DIR / token).is_dir() else None


# ==========================================================================
# Response parsing: '### EDIT:' search/replace blocks and '### FILE:' blocks
# ==========================================================================
#
# The parser is a line-by-line state machine, not a regex over the whole
# reply. That is what lets it (a) never lose a block silently, (b) treat a
# ``` line INSIDE an edit as content rather than a terminator, and (c) say
# exactly which line of the reply was malformed.
#
# Every block-shaped thing it sees is either parsed or reported. There is no
# third outcome.

HEADER_RE = re.compile(
    r"^[ ]{0,3}#{2,4}[ \t]*(?P<kind>FILE|EDIT|PATCH)[ \t]*:[ \t]*(?P<path>.+?)[ \t]*$", re.I)
END_RE = re.compile(r"^[ ]{0,3}#{2,4}[ \t]*END[ \t]+(?:OF[ \t]+)?CHANGES[ \t]*#*[ \t]*$", re.I)
OTHER_HEADER_RE = re.compile(
    r"^[ ]{0,3}#{2,4}[ \t]*(?P<kind>[A-Za-z][A-Za-z _-]{1,24}?)[ \t]*:[ \t]*(?P<rest>\S.*)$")
FENCE_RE = re.compile(r"^(?P<indent>[ ]{0,3})(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
SEARCH_RE = re.compile(r"^<{4,9}[ \t]*(?:SEARCH)?[ \t]*$", re.I)
DIVIDER_RE = re.compile(r"^={4,9}[ \t]*$")
REPLACE_RE = re.compile(r"^>{4,9}[ \t]*(?:REPLACE)?[ \t]*$", re.I)
# Something that is TRYING to be a marker but is not one we accept (indented,
# 3 characters, trailing junk). Reported, never guessed at.
NEAR_MARKER_RE = re.compile(r"^[ \t]*(?:<{4,}|>{4,}|<{3}[ \t]*SEARCH\b|>{3}[ \t]*REPLACE\b)", re.I)
UDIFF_RE = re.compile(r"^(?:diff --git |--- a/|\+\+\+ b/|@@ -\d+(?:,\d+)? \+\d+)")
PATHLIKE_RE = re.compile(r"^(?:[\w.@+-]+[/\\])*[\w.@+-]+\.[A-Za-z0-9_]{1,10}$")
# Block types a model might invent that mean "change the repo". Seeing one is
# an error, because silently ignoring it is how half a change gets applied.
CHANGE_INTENT_WORDS = {
    "create", "update", "modify", "replace", "diff", "delete", "remove", "rename",
    "move", "new file", "newfile", "append", "insert", "write",
}
# Placeholder text that stands in for code. Inside a FILE body or a REPLACE
# side it means "the model summarised instead of writing", and applying it
# would delete real code.
ELISION = [
    re.compile(r"(?im)^\s*(?:#|//|/\*|<!--|--)?\s*\.{3,}\s*\(?\s*(?:rest|remainder|remaining|the rest|unchanged|existing|same)\b"),
    re.compile(r"(?im)\b(?:rest|remainder) of (?:the )?(?:file|function|class|code)\s+(?:is\s+)?(?:unchanged|the same|omitted|as before)"),
    re.compile(r"(?im)^\s*(?:#|//|/\*|<!--|--)?\s*(?:\.{3,}|\u2026)\s*(?:existing|previous|unchanged|other)\s+(?:code|methods|imports|content)"),
    re.compile(r"(?im)\bomitted for brevity\b"),
    re.compile(r"(?im)^\s*(?:#|//)\s*\.{3,}\s*$"),
]
LOOSE_HEADER_RE = re.compile(r"^[ \t>*_#`]*(?:FILE|EDIT|PATCH)[*_`]*[ \t]*:[ \t]*\S", re.I)
MARKDOWNISH = {".md", ".markdown", ".rst", ".txt", ".mdx"}


@dataclass
class EditBlock:
    search: str          # literal text, LF line endings, ends with '\n' unless empty
    replace: str         # literal text, LF line endings, ends with '\n' unless empty
    line: int            # 1-based line of the SEARCH marker in the reply

    def to_json(self) -> Dict[str, Any]:
        return {"search": self.search, "replace": self.replace, "line": self.line}

    @staticmethod
    def from_json(d: Dict[str, Any]) -> "EditBlock":
        return EditBlock(search=d["search"], replace=d["replace"], line=int(d.get("line", 0)))


@dataclass
class ParsedBlock:
    kind: str                         # "edit" | "file"
    path: str                         # as the model wrote it (cleaned of wrappers)
    line: int                         # reply line of the header (or of the block)
    edit: Optional[EditBlock] = None
    content: Optional[str] = None
    style: str = "header"             # "header" | "aider"


@dataclass
class ParseProblem:
    line: int
    message: str
    path: Optional[str] = None        # raw path the problem belongs to, when known
    severity: str = "error"           # "error" blocks applying; "warning" does not


@dataclass
class ParseResult:
    blocks: List[ParsedBlock] = field(default_factory=list)
    problems: List[ParseProblem] = field(default_factory=list)
    end_marker: bool = False
    blocks_after_end: int = 0
    announced: List[Tuple[int, str, str]] = field(default_factory=list)   # (line, path, kind)

    @property
    def errors(self) -> List[ParseProblem]:
        return [p for p in self.problems if p.severity == "error"]

    @property
    def warnings(self) -> List[ParseProblem]:
        return [p for p in self.problems if p.severity != "error"]


ANNOUNCE_RE = re.compile(
    r"^[ \t]*(?:[-*+]|\d+[.)])?[ \t]*[`*]*(?P<path>[\w.@+-]+(?:[/\\][\w.@+-]+)*\.[A-Za-z0-9_]{1,10})[`*]*"
    r"[ \t]*(?:[-\u2013\u2014:|>]|\u2192)+[ \t]*[`*]*(?P<kind>EDIT|FILE)\b", re.I)


def _join_lines(lines: List[str]) -> str:
    return ("\n".join(lines) + "\n") if lines else ""


def _clean_header_path(raw: str) -> str:
    """'`a/b.py` (adds X)' -> 'a/b.py'. Only strips a trailing description
    when it is unmistakably one; a path is never guessed."""
    s = raw.strip()
    m = re.match(r"^(`+|\*\*|\*|\"|')(.+?)\1(.*)$", s)
    if m:
        s = m.group(2) + m.group(3)
    s = s.strip().rstrip(":").strip()
    if " " in s:
        first, rest = s.split(" ", 1)
        if rest.lstrip()[:1] in ("(", "-", "\u2014", "\u2013", "#", "[") and PATHLIKE_RE.match(first.strip("`*")):
            s = first
    return s.strip("`*").strip()


def parse_changes(text: str) -> ParseResult:
    """Parse a model reply into change blocks. Never drops anything silently."""
    res = ParseResult()
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    n = len(lines)
    i = 0
    section_path: Optional[str] = None      # set while inside an EDIT section
    section_style = "header"
    section_blocks = 0
    section_line = 0

    def close_section() -> None:
        nonlocal section_path, section_blocks
        if section_path is not None and section_blocks == 0:
            res.problems.append(ParseProblem(
                section_line, f"'### EDIT: {section_path}' has no SEARCH/REPLACE block under it",
                path=section_path))
        section_path = None
        section_blocks = 0

    def after_end() -> bool:
        return res.end_marker

    def parse_edit(start: int, path: str, style: str) -> int:
        """lines[start] is a SEARCH marker. Returns the index after the block."""
        j = start + 1
        search: List[str] = []
        while j < n:
            ln = lines[j]
            if DIVIDER_RE.match(ln):
                break
            if SEARCH_RE.match(ln):
                res.problems.append(ParseProblem(
                    j + 1, "a second SEARCH marker appeared before the '=======' divider "
                           "(the previous block was never finished)", path=path))
                return j
            if REPLACE_RE.match(ln):
                res.problems.append(ParseProblem(
                    j + 1, "REPLACE marker found before the '=======' divider", path=path))
                return j + 1
            search.append(ln)
            j += 1
        if j >= n:
            res.problems.append(ParseProblem(
                start + 1, "edit block never reached its '=======' divider - the reply was "
                           "cut off here (truncated output)", path=path))
            return n
        j += 1
        replace: List[str] = []
        while j < n:
            ln = lines[j]
            if REPLACE_RE.match(ln):
                break
            if DIVIDER_RE.match(ln):
                res.problems.append(ParseProblem(
                    j + 1, "a second '=======' divider inside one block - ambiguous. This "
                           "happens when the file itself contains a '=======' line; that region "
                           "must be sent as a FILE block instead", path=path))
                k = j + 1
                while k < n and not REPLACE_RE.match(lines[k]):
                    k += 1
                return min(k + 1, n)
            if SEARCH_RE.match(ln):
                res.problems.append(ParseProblem(
                    j + 1, "a new SEARCH marker appeared before '>>>>>>> REPLACE' closed the "
                           "previous block", path=path))
                return j
            replace.append(ln)
            j += 1
        if j >= n:
            res.problems.append(ParseProblem(
                start + 1, "edit block never reached '>>>>>>> REPLACE' - the reply was cut off "
                           "here (truncated output)", path=path))
            return n
        blk = EditBlock(search=_join_lines(search), replace=_join_lines(replace), line=start + 1)
        if after_end():
            res.blocks_after_end += 1
        else:
            res.blocks.append(ParsedBlock("edit", path, start + 1, edit=blk, style=style))
        return j + 1

    def parse_file(hdr: int, path: str) -> int:
        j = hdr + 1
        while j < n and not lines[j].strip() and j - hdr <= 3:
            j += 1
        m = FENCE_RE.match(lines[j]) if j < n else None
        if not m:
            res.problems.append(ParseProblem(
                hdr + 1, f"'### FILE: {path}' is not followed by a fenced code block", path=path))
            return hdr + 1
        ch, width = m.group("fence")[0], len(m.group("fence"))
        j += 1
        body: List[str] = []
        closed = False
        while j < n:
            fm = FENCE_RE.match(lines[j])
            if (fm and fm.group("fence")[0] == ch and len(fm.group("fence")) >= width
                    and not fm.group("info").strip()):
                closed = True
                break
            body.append(lines[j])
            j += 1
        if not closed:
            res.problems.append(ParseProblem(
                hdr + 1, f"FILE block for {path} has no closing fence - the reply was cut off "
                         f"inside it (truncated output). Nothing from it is staged.", path=path))
            return n
        # Early-close check: a markdown file that contains its own ``` lines,
        # fenced with only ```, closes at the file's first inner fence. The
        # rest of the file then trails the block as "prose" with more fences.
        k = j + 1
        while k < n and not (HEADER_RE.match(lines[k]) or END_RE.match(lines[k])
                             or SEARCH_RE.match(lines[k])):
            fm = FENCE_RE.match(lines[k])
            if fm and fm.group("fence")[0] == ch:
                suffix = Path(path).suffix.lower()
                res.problems.append(ParseProblem(
                    hdr + 1,
                    f"FILE block for {path} may have been cut short at a ``` line inside the "
                    f"file (more fences follow it at reply line {k + 1}). A file that contains "
                    f"``` must be fenced with a LONGER run, e.g. ````",
                    path=path, severity="error" if suffix in MARKDOWNISH else "warning"))
                break
            k += 1
        if after_end():
            res.blocks_after_end += 1
        else:
            res.blocks.append(ParsedBlock("file", path, hdr + 1, content=_join_lines(body)))
        return j + 1

    def aider_path_before(idx: int) -> Optional[str]:
        """Aider style: the path on its own line just above the block
        (optionally with a fence line in between). Exact path tokens only."""
        k = idx - 1
        while k >= 0 and not lines[k].strip():
            k -= 1
        if k >= 0 and FENCE_RE.match(lines[k]):
            k -= 1
            while k >= 0 and not lines[k].strip():
                k -= 1
        if k < 0:
            return None
        cand = lines[k].strip().strip("`*").strip()
        return cand if PATHLIKE_RE.match(cand) else None

    while i < n:
        ln = lines[i]

        hm = HEADER_RE.match(ln)
        if hm:
            close_section()
            kind = hm.group("kind").lower()
            path = _clean_header_path(hm.group("path"))
            if kind == "file":
                i = parse_file(i, path)
                continue
            section_path, section_style, section_blocks, section_line = path, "header", 0, i + 1
            i += 1
            continue

        if END_RE.match(ln):
            close_section()
            res.end_marker = True
            i += 1
            continue

        if SEARCH_RE.match(ln):
            owner: Optional[str] = section_path
            style = section_style
            if owner is None:
                owner = aider_path_before(i)
                style = "aider"
                if owner is None:
                    res.problems.append(ParseProblem(
                        i + 1, "SEARCH/REPLACE block with no '### EDIT: <path>' header above it - "
                               "cannot tell which file it belongs to"))
                    # consume it so its content is not re-scanned as top-level text
                    j = i + 1
                    while j < n and not REPLACE_RE.match(lines[j]):
                        j += 1
                    i = j + 1
                    continue
                section_path, section_style, section_blocks, section_line = owner, "aider", 0, i + 1
            i = parse_edit(i, owner, style)
            section_blocks += 1
            continue

        if section_path is not None:
            stripped = ln.strip()
            if (not stripped or FENCE_RE.match(ln)
                    or stripped.strip("`*").strip() == section_path):
                i += 1
                continue
            if NEAR_MARKER_RE.match(ln) or DIVIDER_RE.match(stripped):
                res.problems.append(ParseProblem(
                    i + 1, f"malformed edit marker {stripped[:40]!r} - markers must start at "
                           f"column 0 and be exactly '<<<<<<< SEARCH', '=======', "
                           f"'>>>>>>> REPLACE'", path=section_path))
                i += 1
                continue
            close_section()      # prose ends an EDIT section
            continue

        if NEAR_MARKER_RE.match(ln):
            res.problems.append(ParseProblem(
                i + 1, f"malformed edit marker {ln.strip()[:40]!r} outside any EDIT section"))
            i += 1
            continue

        if LOOSE_HEADER_RE.match(ln) and not after_end():
            nxt = [x for x in lines[i + 1:i + 4] if x.strip()][:1]
            if nxt and (FENCE_RE.match(nxt[0]) or SEARCH_RE.match(nxt[0])):
                res.problems.append(ParseProblem(
                    i + 1, f"change header not recognised: {ln.strip()[:60]!r} - it must be "
                           f"'### FILE: <path>' or '### EDIT: <path>' on its own line"))
                i += 1
                continue

        om = OTHER_HEADER_RE.match(ln)
        if om:
            word = om.group("kind").strip().lower()
            nxt = [x for x in lines[i + 1:i + 4] if x.strip()][:2]
            block_shaped = any(FENCE_RE.match(x) or SEARCH_RE.match(x) for x in nxt)
            if block_shaped and not after_end() and (
                    word in CHANGE_INTENT_WORDS or PATHLIKE_RE.match(om.group("rest").strip("`* "))):
                hint = ("kimicli never deletes, renames or moves files - do that step by hand "
                        "(retire.py), then continue" if word in ("delete", "remove", "rename", "move")
                        else "only '### EDIT:' and '### FILE:' blocks are applied")
                res.problems.append(ParseProblem(
                    i + 1, f"unsupported block type '### {om.group('kind').strip()}:' - {hint}",
                    path=om.group("rest").strip("`* ")))
            i += 1
            continue

        fm = FENCE_RE.match(ln)
        if fm and i + 1 < n and UDIFF_RE.match(lines[i + 1]) and not after_end():
            res.problems.append(ParseProblem(
                i + 1, "the reply contains a unified diff; kimicli does not apply diffs. If it "
                       "was meant as a change, ask for EDIT blocks", severity="warning"))
        i += 1

    close_section()
    first = min((b.line for b in res.blocks), default=n + 1)
    for k in range(0, min(first - 1, n)):
        am = ANNOUNCE_RE.match(lines[k])
        if am and not HEADER_RE.match(lines[k]):
            res.announced.append((k + 1, am.group("path"), am.group("kind").lower()))
    if res.blocks_after_end:
        res.problems.append(ParseProblem(
            0, f"{res.blocks_after_end} change block(s) after '### END CHANGES' were NOT staged "
               f"(that part of a reply is for discussion, e.g. BETTER IDEA code)", severity="warning"))
    return res


# ==========================================================================
# Paths: normalisation, safety, and a one-walk index of the repo
# ==========================================================================

class PathRefused(Exception):
    pass


_WIN_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[0-9\u00b9\u00b2\u00b3]|"
                           r"LPT[0-9\u00b9\u00b2\u00b3])(?:\..*)?$", re.I)
_SHORT_NAME = re.compile(r"~\d")
_BAD_WIN_CHARS = set('<>|?*"')
PRUNE_DIRS = {".git", ".hg", ".svn", ".venv", "venv", "env", "node_modules", "__pycache__",
              ".kimi_out", ".kimi_backups", ".ds_backups", ".mypy_cache", ".pytest_cache",
              ".ruff_cache", ".tox", ".nox", ".idea", ".vscode", ".eggs"}
_PROTECTED_CF = {p.casefold() for p in PROTECTED}


def normalize_rel(raw: str, root: Path) -> str:
    """Model-written path -> clean repo-relative 'a/b/c.py', or PathRefused.
    Deterministic: nothing here consults the filesystem except the one
    repo-name check below."""
    s = raw.strip().strip("`'\"*").strip()
    if not s:
        raise PathRefused("empty path")
    if any(ord(c) < 32 for c in s):
        raise PathRefused("control character in path")
    s = s.replace("\\", "/")
    if s.startswith("//"):
        raise PathRefused("network (UNC) path refused - use a repo-relative path")
    if re.match(r"^[A-Za-z]:", s):
        raise PathRefused("drive-qualified path refused - use a repo-relative path")
    while s.startswith("./"):
        s = s[2:]
    s = s.lstrip("/")
    parts = [p for p in s.split("/") if p not in ("", ".")]
    if not parts:
        raise PathRefused("path has no file name")
    for p in parts:
        if p == "..":
            raise PathRefused("'..' is not allowed in a path")
        if ":" in p:
            raise PathRefused(f"':' in {p!r} refused (would write an NTFS alternate data stream)")
        if p != p.rstrip(" ."):
            raise PathRefused(f"{p!r} ends with a dot or space (Windows silently aliases those)")
        if _WIN_RESERVED.match(p):
            raise PathRefused(f"{p!r} is a reserved Windows device name")
        if _SHORT_NAME.search(p):
            raise PathRefused(f"{p!r} looks like a Windows 8.3 short name (can alias another file)")
        if any(c in _BAD_WIN_CHARS for c in p):
            raise PathRefused(f"{p!r} contains a character Windows does not allow in file names")
    # The repo dump labels files 'AA/packages/...' (the GitHub repo name),
    # whatever your local folder is called. Strip a leading folder ONLY when it
    # does not exist here AND it is either named like this folder or followed
    # by a folder that does exist at the top of the repo. Never otherwise.
    if (len(parts) > 2 and not (root / parts[0]).is_dir()
            and (parts[0].casefold() == root.name.casefold() or (root / parts[1]).is_dir())):
        parts = parts[1:]
    elif len(parts) == 2 and parts[0].casefold() == root.name.casefold() and not (root / parts[0]).is_dir():
        parts = parts[1:]
    return "/".join(parts)


def is_protected_rel(rel: str) -> bool:
    return any(part.casefold() in _PROTECTED_CF for part in rel.split("/"))


def safe_target(root: Path, rel: str) -> Path:
    """Absolute target for a normalised rel path. Refuses links and escapes."""
    root_res = root.resolve()
    cur = root
    for part in rel.split("/"):
        cur = cur / part
        if cur.is_symlink():
            raise PathRefused(f"{cur.relative_to(root).as_posix()!r} is a symbolic link; "
                              f"kimicli never writes through links")
        isjunction = getattr(os.path, "isjunction", None)
        if isjunction is not None and isjunction(cur):
            raise PathRefused(f"{cur.relative_to(root).as_posix()!r} is a junction; refused")
        if not cur.exists():
            break
    target = root.joinpath(*rel.split("/"))
    try:
        target.resolve().relative_to(root_res)
    except (ValueError, OSError):
        raise PathRefused("path resolves outside the project root")
    return target


def canonical_case(root: Path, rel: str) -> str:
    """On a case-insensitive filesystem (Windows), 'PKG/A.py' opens pkg/a.py.
    Return the on-disk spelling so a write never renames the file. On a
    case-sensitive filesystem a wrong-case path simply does not exist, and is
    returned unchanged - never re-routed."""
    if not root.joinpath(*rel.split("/")).exists():
        return rel
    out: List[str] = []
    cur = root
    for part in rel.split("/"):
        try:
            names = [n for n in os.listdir(cur) if n.casefold() == part.casefold()]
        except OSError:
            names = []
        actual = part if part in names or len(names) != 1 else names[0]
        out.append(actual)
        cur = cur / actual
    return "/".join(out)


class FileIndex:
    """Every file under the root, walked once, skipping venvs/caches/.git."""

    def __init__(self, root: Path):
        self.root = root
        self.rel: List[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS and not d.endswith(".egg-info")]
            base = Path(dirpath).relative_to(root).as_posix()
            for f in filenames:
                rel = f if base == "." else f"{base}/{f}"
                # Protected files (retired code, personal data, the tools
                # themselves) are never edit targets or import sources.
                if not is_protected_rel(rel):
                    self.rel.append(rel)
        self._cf = [r.casefold() for r in self.rel]
        self._set = set(self.rel)

    def suffix_matches(self, rel: str) -> List[str]:
        """Files whose path ENDS WITH rel, component-aligned, excluding rel itself."""
        want = "/" + rel.casefold()
        return [r for r, c in zip(self.rel, self._cf) if c.endswith(want)]

    def basename_matches(self, name: str) -> List[str]:
        n = name.casefold()
        return [r for r, c in zip(self.rel, self._cf) if c.rsplit("/", 1)[-1] == n]

    def module_file(self, dotted: str) -> Optional[str]:
        """'auto_apply.domain.x' -> the unique repo file for it, else None.
        The file must sit at an import ROOT: the folder holding the first
        package name must not itself be a package. Otherwise 'types' would
        resolve to auto_apply/domain/types.py and shadow the stdlib."""
        if not dotted:
            return None
        tail = dotted.replace(".", "/")
        hits = self.suffix_matches(tail + ".py") + self.suffix_matches(tail + "/__init__.py")
        hits += [c for c in (tail + ".py", tail + "/__init__.py") if c in self._set]
        depth = dotted.count(".") + 1
        rooted = []
        for h in sorted(set(hits)):
            parts = h.split("/")
            if parts[-1] == "__init__.py":
                parts = parts[:-1]
            else:
                parts[-1] = parts[-1][:-3]
            container = "/".join(parts[:len(parts) - depth])
            init = (container + "/__init__.py") if container else "__init__.py"
            if init not in self._set:
                rooted.append(h)
        return rooted[0] if len(rooted) == 1 else None


# ==========================================================================
# Bytes-exact text handling
# ==========================================================================

UTF8_BOM = b"\xef\xbb\xbf"


class NotText(Exception):
    pass


def decode_strict(raw: bytes) -> Tuple[str, bool]:
    """(text, had_bom). Refuses anything that would not round-trip exactly:
    rewriting a file decoded with errors='replace' destroys every byte that
    was not UTF-8, anywhere in the file."""
    bom = raw.startswith(UTF8_BOM)
    body = raw[3:] if bom else raw
    if b"\x00" in body:
        raise NotText("contains NUL bytes (binary file)")
    try:
        return body.decode("utf-8"), bom
    except UnicodeDecodeError as exc:
        raise NotText(f"is not valid UTF-8 (first bad byte at offset {exc.start}); editing it "
                      f"would corrupt it")


def encode_text(text: str, bom: bool) -> bytes:
    return (UTF8_BOM if bom else b"") + text.encode("utf-8")


def dominant_eol(text: str) -> str:
    crlf = text.count("\r\n")
    return "\r\n" if crlf and crlf > text.count("\n") - crlf else "\n"


def normalise_for_compare(s: str) -> str:
    return "\n".join(ln.rstrip() for ln in s.replace("\r\n", "\n").replace("\r", "\n").split("\n")).strip("\n")


# ==========================================================================
# The edit engine: exact, unique, line-ending-preserving search/replace
# ==========================================================================

@dataclass
class EditOutcome:
    index: int                    # 1-based position within the file's blocks
    status: str                   # "applied" | "have" | "failed"
    how: str = ""
    problem: str = ""
    reply_line: int = 0
    diag: Optional[Dict[str, Any]] = None   # closest-match info for the repair prompt


def _find_all(hay: str, needle: str) -> List[int]:
    out: List[int] = []
    if not needle:
        return out
    start = 0
    while True:
        k = hay.find(needle, start)
        if k < 0:
            return out
        out.append(k)
        start = k + 1


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _normalise_with_map(text: str) -> Tuple[str, List[int]]:
    """Drop the '\\r' of every '\\r\\n'. Returns (normalised, crs) where crs is
    the sorted list of NORMALISED offsets of each '\\n' that lost its '\\r'."""
    crs: List[int] = []
    out: List[str] = []
    k = 0
    pos = 0
    L = len(text)
    while k < L:
        nxt = text.find("\r\n", k)
        if nxt < 0:
            out.append(text[k:])
            break
        out.append(text[k:nxt])
        pos += nxt - k
        crs.append(pos)            # the '\n' lands at normalised offset `pos`
        out.append("\n")
        pos += 1
        k = nxt + 2
    return "".join(out), crs


def _to_original(offset: int, crs: List[int]) -> int:
    return offset + bisect.bisect_left(crs, offset)


def closest_region(norm: str, search: str) -> Dict[str, Any]:
    """Where in the file the SEARCH text most nearly appears. For the repair
    prompt only - never used to decide where to write."""
    flines = norm.split("\n")
    slines = search.rstrip("\n").split("\n") if search else [""]
    k = max(1, len(slines))
    target = "\n".join(slines)
    anchors = {s.strip() for s in slines if len(s.strip()) >= 8}
    candidates: List[int] = []
    if anchors:
        for idx, fl in enumerate(flines):
            if fl.strip() in anchors:
                for off in range(k):
                    if 0 <= idx - off <= max(0, len(flines) - k):
                        candidates.append(idx - off)
    if not candidates:
        candidates = list(range(0, max(1, len(flines) - k + 1)))
    candidates = sorted(set(candidates))[:6000]
    best_i, best_r = 0, -1.0
    for idx in candidates:
        window = "\n".join(flines[idx:idx + k])
        sm = difflib.SequenceMatcher(None, window, target, autojunk=False)
        if sm.real_quick_ratio() <= best_r or sm.quick_ratio() <= best_r:
            continue
        r = sm.ratio()
        if r > best_r:
            best_i, best_r = idx, r
    lo = max(0, best_i - 3)
    hi = min(len(flines), best_i + k + 3)
    excerpt = "\n".join(f"{n + 1:>6}| {flines[n]}" for n in range(lo, hi))
    return {"line": best_i + 1, "ratio": round(max(best_r, 0.0), 2), "excerpt": excerpt}


def apply_edits(original: str, edits: List[EditBlock]) -> Tuple[str, List[EditOutcome]]:
    """Apply edits in order to `original` (decoded text, ORIGINAL line
    endings). Untouched bytes are preserved exactly, including mixed line
    endings. Returns (new_text, outcomes); new_text is meaningful only when no
    outcome failed."""
    cur = original
    outcomes: List[EditOutcome] = []
    for idx, ed in enumerate(edits, 1):
        oc = EditOutcome(index=idx, status="failed", reply_line=ed.line)
        outcomes.append(oc)
        S = ed.search.replace("\r\n", "\n")
        R = ed.replace.replace("\r\n", "\n")
        norm, crs = _normalise_with_map(cur)
        virtual = bool(norm) and not norm.endswith("\n")
        hay = norm + "\n" if virtual else norm

        if not S.strip():
            oc.problem = ("SEARCH is empty. To insert, SEARCH an adjacent existing line and "
                          "REPLACE it with that line plus the new ones; to create a file, use FILE")
            continue
        if S == R:
            oc.status, oc.how = "have", "SEARCH and REPLACE are identical (no-op)"
            continue

        # Matches must start at the beginning of a line. A SEARCH is whole
        # lines; letting 'x = 1' match the tail of 'max = 1' would edit the
        # wrong line silently.
        s_sites = [p for p in _find_all(hay, S) if p == 0 or hay[p - 1] == "\n"]
        r_sites = ([p for p in _find_all(hay, R) if p == 0 or hay[p - 1] == "\n"]
                   if R.strip() else [])
        additive = bool(R) and S in R
        if additive and r_sites:
            s_sites = [p for p in s_sites
                       if not any(r <= p and p + len(S) <= r + len(R) for r in r_sites)]

        start = end = -1
        if len(s_sites) == 1 and not (additive and r_sites):
            start, end = s_sites[0], s_sites[0] + len(S)
            oc.how = "exact"
        elif len(s_sites) > 1:
            where = ", ".join(str(_line_of(hay, p)) for p in s_sites[:6])
            oc.problem = (f"SEARCH matches {len(s_sites)} places (lines {where}); add unchanged "
                          f"neighbouring lines until it is unique")
            continue
        elif additive and s_sites and r_sites:
            oc.problem = ("conflict: the text this block adds is already present, AND its SEARCH "
                          "anchor appears elsewhere un-applied - refusing to guess which is meant")
            continue
        elif not s_sites and len(r_sites) == 1 and (R.strip().count("\n") >= 1 or len(R.strip()) >= 30):
            oc.status, oc.how = "have", f"already applied (REPLACE text present at line {_line_of(hay, r_sites[0])})"
            continue
        else:
            # One tolerated difference: trailing whitespace. Whole lines only.
            flines = hay.split("\n")
            slines = S.rstrip("\n").split("\n")
            kk = len(slines)
            want = [x.rstrip() for x in slines]
            stripped = [x.rstrip() for x in flines]
            hits = [a for a in range(0, len(flines) - kk + 1) if stripped[a:a + kk] == want]
            if additive and r_sites:
                starts = {a: sum(len(x) + 1 for x in flines[:a]) for a in hits}
                hits = [a for a in hits
                        if not any(r <= starts[a] < r + len(R) for r in r_sites)]
            if len(hits) == 1:
                a = hits[0]
                start = sum(len(x) + 1 for x in flines[:a])
                end = start + sum(len(x) + 1 for x in flines[a:a + kk])
                oc.how = "matched ignoring trailing whitespace"
            elif len(hits) > 1:
                oc.problem = (f"SEARCH matches {len(hits)} places when trailing whitespace is ignored "
                              f"(lines {', '.join(str(h + 1) for h in hits[:6])}); make it unique")
                continue
            else:
                diag = closest_region(norm, S)
                elided = any(p.search(S) for p in ELISION)
                oc.problem = ("SEARCH text not found in the file"
                              + (" - it contains a placeholder like '...', but SEARCH must be literal "
                                 "text copied from the file" if elided else
                                 f" (closest region: line {diag['line']}, {int(diag['ratio'] * 100)}% similar)"))
                oc.diag = diag
                continue

        repl = R
        if virtual and end > len(norm):
            end = len(norm)
            if repl.endswith("\n"):
                repl = repl[:-1]
        o_start, o_end = _to_original(start, crs), _to_original(end, crs)
        if dominant_eol(cur) == "\r\n":
            repl = repl.replace("\n", "\r\n")
        cur = cur[:o_start] + repl + cur[o_end:]
        oc.status = "applied"
    return cur, outcomes


# ==========================================================================
# Code checks: catch the change that parses but cannot run
# ==========================================================================
#
# All of these compare BEFORE and AFTER, and report only what the change
# introduces - a pre-existing problem is not this batch's fault and must not
# block it. Each is conservative: when a check cannot be sure, it stays quiet.

_IMPLICIT_GLOBALS = {"__file__", "__name__", "__doc__", "__builtins__", "__spec__", "__loader__",
                     "__package__", "__path__", "__annotations__", "__cached__", "__dict__",
                     "__module__", "__qualname__", "__class__", "__debug__", "WindowsError"}


def undefined_names(src: str) -> Optional[set]:
    """Names referenced at run time that nothing defines (ruff F821's core).
    None = could not analyse (syntax error, star import)."""
    import builtins
    try:
        top = symtable.symtable(src, "<kimicli>", "exec")
    except (SyntaxError, ValueError):
        return None
    if re.search(r"(?m)^\s*from\s+\S+\s+import\s+\*", src):
        return None
    defined: set = set()

    def collect(t: Any) -> None:
        for s in t.get_symbols():
            if t.get_type() == "module" and (s.is_assigned() or s.is_imported() or s.is_namespace()):
                defined.add(s.get_name())
            elif t.get_type() != "module" and s.is_declared_global() and s.is_assigned():
                defined.add(s.get_name())
        for c in t.get_children():
            collect(c)

    collect(top)
    known = defined | set(dir(builtins)) | _IMPLICIT_GLOBALS
    missing: set = set()

    def walk(t: Any) -> None:
        if "annotation" in str(t.get_type()).lower():
            return
        for s in t.get_symbols():
            if not s.is_referenced():
                continue
            free_global = s.is_global() or (
                t.get_type() == "module" and not (s.is_assigned() or s.is_imported()))
            if free_global and s.get_name() not in known:
                missing.add(s.get_name())
        for c in t.get_children():
            walk(c)

    walk(top)
    return missing


def module_top_names(tree: "ast.Module") -> Tuple[set, bool]:
    """(names a module defines at top level, dynamic). dynamic=True means the
    module can produce names this analysis cannot see (star import or a
    module-level __getattr__), so importers must not be judged against it."""
    names: set = set()
    dynamic = False

    def targets(node: Any) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for e in node.elts:
                targets(e)
        elif isinstance(node, ast.Starred):
            targets(node.value)

    def visit(body: List[Any]) -> None:
        nonlocal dynamic
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                if node.name == "__getattr__" and not isinstance(node, ast.ClassDef):
                    dynamic = True
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Global):
                        names.update(sub.names)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    targets(t)
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets(node.target)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for a in node.names:
                    if a.name == "*":
                        dynamic = True
                    else:
                        names.add(a.asname or a.name.split(".")[0])
            elif isinstance(node, (ast.For, ast.AsyncFor)):
                targets(node.target)
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, (ast.With, ast.AsyncWith)):
                for it in node.items:
                    if it.optional_vars is not None:
                        targets(it.optional_vars)
                visit(node.body)
            elif isinstance(node, (ast.If, ast.While)):
                visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
                visit(node.body)
                for h in node.handlers:
                    if h.name:
                        names.add(h.name)
                    visit(h.body)
                visit(node.orelse)
                visit(node.finalbody)
            elif type(node).__name__ == "Match":
                for case in node.cases:
                    visit(case.body)
            elif type(node).__name__ == "TypeAlias":
                targets(node.name)
            for sub in ast.walk(node) if not isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)) else []:
                if isinstance(sub, ast.NamedExpr):
                    targets(sub.target)

    visit(tree.body)
    return names, dynamic


def _resolve_from_import(node: "ast.ImportFrom", importer_rel: str, index: "FileIndex") -> Optional[str]:
    """Repo file the `from X import ...` refers to, or None when external/unsure."""
    if node.level == 0:
        return index.module_file(node.module or "") if node.module else None
    base = importer_rel.split("/")[:-1]
    up = node.level - 1
    if up > len(base):
        return None
    base = base[:len(base) - up] if up else base
    mod_parts = (node.module or "").split(".") if node.module else []
    cand = "/".join(base + mod_parts)
    have = index._set
    if cand + ".py" in have:
        return cand + ".py"
    if cand + "/__init__.py" in have:
        return cand + "/__init__.py"
    return None


def cross_file_problems(changed: Dict[str, Tuple[Optional[str], str]], index: "FileIndex",
                        read_current: Any) -> Dict[str, List[str]]:
    """changed: rel -> (old_text or None, new_text), .py files only.
    Finds (1) new `from X import n` in a changed file where X (after this
    batch) does not define n, and (2) names a changed module REMOVES that an
    unchanged file still imports. Returns rel -> problems."""
    out: Dict[str, List[str]] = {}
    cache: Dict[str, Optional[Tuple[set, bool]]] = {}

    def names_after(rel: str) -> Optional[Tuple[set, bool]]:
        if rel in cache:
            return cache[rel]
        text = changed[rel][1] if rel in changed else read_current(rel)
        try:
            val = module_top_names(ast.parse(text)) if text is not None else None
        except SyntaxError:
            val = None
        cache[rel] = val
        return val

    def is_submodule(mod_rel: str, name: str) -> bool:
        if not mod_rel.endswith("__init__.py"):
            return False
        pkg = mod_rel[: -len("__init__.py")]
        have = index._set | set(changed)
        return (pkg + name + ".py") in have or (pkg + name + "/__init__.py") in have

    def imports_of(text: str, rel: str) -> List[Tuple[str, str, int]]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        # An import inside `try: ... except ImportError:` is optional by
        # design; never judge it.
        guarded: set = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try) or type(node).__name__ == "TryStar":
                names = set()
                for h in node.handlers:  # type: ignore[attr-defined]
                    if h.type is None:
                        names.add("*")
                    for t in (h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]) if h.type else []:
                        if isinstance(t, ast.Name):
                            names.add(t.id)
                        elif isinstance(t, ast.Attribute):
                            names.add(t.attr)
                if names & {"*", "ImportError", "ModuleNotFoundError", "Exception", "BaseException"}:
                    for stmt in node.body:  # type: ignore[attr-defined]
                        for sub in ast.walk(stmt):
                            guarded.add(id(sub))
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and id(node) not in guarded:
                target = _resolve_from_import(node, rel, index)
                if target:
                    for a in node.names:
                        if a.name != "*":
                            found.append((target, a.name, node.lineno))
        return found

    # (1) imports a changed file makes
    for rel, (old_text, new_text) in changed.items():
        before = {(t, nm) for t, nm, _ in imports_of(old_text, rel)} if old_text else set()
        for target, name, lineno in imports_of(new_text, rel):
            if (target, name) in before and target not in changed:
                continue          # untouched import of an untouched module: not ours
            info = names_after(target)
            if info is None or info[1]:
                continue
            if name not in info[0] and not is_submodule(target, name):
                out.setdefault(rel, []).append(
                    f"line {lineno}: imports {name!r} from {target}, which does not define it "
                    f"after this change (ImportError at import time)")

    # (2) names a changed module drops that the rest of the repo still imports
    for rel, (old_text, _new) in changed.items():
        if not old_text:
            continue
        try:
            before_names, dyn_b = module_top_names(ast.parse(old_text))
        except SyntaxError:
            continue
        after = names_after(rel)
        if after is None or after[1] or dyn_b:
            continue
        removed = before_names - after[0]
        if not removed:
            continue
        stem = rel.rsplit("/", 1)[-1][:-3]
        if stem == "__init__":
            stem = rel.rsplit("/", 2)[-2]
        pattern = re.compile(r"\b(" + "|".join(re.escape(x) for x in sorted(removed)) + r")\b")
        for other in index.rel:
            if not other.endswith(".py") or other in changed:
                continue
            text = read_current(other)
            if not text or stem not in text or not pattern.search(text):
                continue
            for target, name, lineno in imports_of(text, other):
                if target == rel and name in removed:
                    out.setdefault(rel, []).append(
                        f"removes {name!r}, but {other}:{lineno} still imports it "
                        f"(that file would fail to import)")
    return out


def validate_syntax(rel: str, text: str) -> Optional[str]:
    suffix = Path(rel).suffix.lower()
    if suffix == ".py":
        try:
            compile(text, rel, "exec", dont_inherit=True)
        except SyntaxError as exc:
            return f"Python syntax error at line {exc.lineno}: {exc.msg}"
        except ValueError as exc:
            return f"Python source rejected: {exc}"
    elif suffix == ".json":
        try:
            json.loads(text)
        except Exception as exc:
            return f"invalid JSON: {exc}"
    elif suffix == ".toml":
        try:
            import tomllib  # Python 3.11+
            tomllib.loads(text)
        except ImportError:
            return None
        except Exception as exc:
            return f"invalid TOML: {exc}"
    return None


def gitattributes_eol(root: Path, rel: str) -> str:
    """Line ending for a NEW file: the repo's .gitattributes decides
    (AA: `* text=auto eol=lf`, `*.bat ... eol=crlf`). Default LF."""
    ga = root / ".gitattributes"
    eol = "\n"
    if not ga.exists():
        return eol
    try:
        lines = ga.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return eol
    name = rel.rsplit("/", 1)[-1]
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        bits = ln.split()
        pat, attrs = bits[0], bits[1:]
        hit = fnmatch.fnmatch(rel, pat.lstrip("/")) if "/" in pat else fnmatch.fnmatch(name, pat)
        if not hit:
            continue
        for a in attrs:
            if a == "eol=crlf":
                eol = "\r\n"
            elif a == "eol=lf":
                eol = "\n"
    return eol


# ==========================================================================
# The applier: resolve against the LIVE tree, validate everything, then write
# transactionally - or write nothing
# ==========================================================================

@dataclass
class Proposal:
    """One file's change, as selected for applying."""
    raw_path: str
    kind: str                                   # "file" | "edit"
    content: Optional[str] = None               # kind == file (LF text)
    edits: List[EditBlock] = field(default_factory=list)
    source: str = ""                            # "turn 3" / "reply.md"
    base_sha: Optional[str] = None              # disk sha when staged ("" = absent); None unknown
    after_sha: Optional[str] = None             # sha of the result computed when staged
    known_bases: List[str] = field(default_factory=list)   # texts Kimi may have based a FILE on
    notes: List[str] = field(default_factory=list)


@dataclass
class ApplyOptions:
    allow_new_files: bool = False
    allow_new_dirs: bool = False
    allow_shrink: bool = False
    allow_stale: bool = False
    skip_checks: bool = False
    shrink_ratio: float = 0.6


@dataclass
class Plan:
    proposal: Proposal
    rel: Optional[str] = None
    target: Optional[Path] = None
    action: str = "update"                      # update | create | identical
    old_bytes: Optional[bytes] = None
    new_bytes: Optional[bytes] = None
    old_text: Optional[str] = None
    new_text: Optional[str] = None
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    outcomes: List[EditOutcome] = field(default_factory=list)
    dirs_to_create: List[str] = field(default_factory=list)

    @property
    def changes(self) -> bool:
        return not self.problems and self.action in ("update", "create")


class ApplyAborted(Exception):
    pass


def _replace_with_retry(src: str, dst: str, attempts: int = 12) -> None:
    """os.replace, retried: on Windows, OneDrive, antivirus and editors hold
    brief locks that make a single attempt fail with PermissionError."""
    delay = 0.05
    for n in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.0)


def write_bytes_atomic(path: Path, data: bytes, keep_mode_of: Optional[Path] = None) -> None:
    """temp file in the same directory -> fsync -> atomic replace. The target
    is either the old bytes or the new bytes; never half of each."""
    fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".kimitmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if keep_mode_of is not None and keep_mode_of.exists():
            try:
                shutil.copymode(str(keep_mode_of), tmp)
            except OSError:
                pass
        _replace_with_retry(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _unlink_with_retry(path: Path, attempts: int = 12) -> None:
    delay = 0.05
    for n in range(attempts):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if n == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.0)


def read_bytes_or_none(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def git_snapshot(root: Path, manifest_id: str) -> Dict[str, Any]:
    """Second, independent safety net: a git commit object of the working
    tree taken BEFORE any write, pinned under refs/kimicli/<id> so it is never
    garbage-collected. `git stash create` touches neither files nor index
    contents. Best effort: no git, no snapshot, no error."""
    if not (root / ".git").exists():
        return {}

    def git(*a: str) -> str:
        r = subprocess.run(["git", *a], cwd=str(root), capture_output=True, text=True, timeout=60)
        return r.stdout.strip() if r.returncode == 0 else ""

    try:
        head = git("rev-parse", "HEAD")
        snap = git("stash", "create", f"kimicli pre-apply {manifest_id}") or head
        ref = ""
        if snap:
            ref = f"refs/kimicli/{manifest_id}"
            if not subprocess.run(["git", "update-ref", ref, snap], cwd=str(root),
                                  capture_output=True, timeout=60).returncode == 0:
                ref = ""
        return {"head": head, "snapshot": snap, "ref": ref}
    except Exception:
        return {}


class Applier:
    def __init__(self, root: Path, backup_dir: Path, options: Optional[ApplyOptions] = None):
        self.root = root.resolve()
        self.backup_dir = backup_dir
        self.opt = options or ApplyOptions()
        self._index: Optional[FileIndex] = None

    @property
    def index(self) -> FileIndex:
        if self._index is None:
            self._index = FileIndex(self.root)
        return self._index

    def _read_current_text(self, rel: str) -> Optional[str]:
        raw = read_bytes_or_none(self.root.joinpath(*rel.split("/")))
        if raw is None:
            return None
        try:
            return decode_strict(raw)[0]
        except NotText:
            return None

    # -- pass 1 -------------------------------------------------------
    def validate(self, proposals: List[Proposal]) -> List[Plan]:
        plans = [self._plan_one(p) for p in proposals]

        seen: Dict[str, Plan] = {}
        for pl in plans:
            if pl.rel is None:
                continue
            key = pl.rel.casefold()
            if key in seen:
                msg = (f"the same file is changed twice in one batch ({seen[key].proposal.raw_path!r} "
                       f"and {pl.proposal.raw_path!r})")
                pl.problems.append(msg)
                if msg not in seen[key].problems:
                    seen[key].problems.append(msg)
            else:
                seen[key] = pl

        if not self.opt.skip_checks:
            py = {pl.rel: pl for pl in plans
                  if pl.rel and pl.rel.endswith(".py") and pl.changes and pl.new_text is not None}
            for pl in py.values():
                new_u = undefined_names(pl.new_text or "")
                old_u = undefined_names(pl.old_text) if pl.old_text is not None else set()
                if new_u is not None and old_u is not None:
                    added = sorted(new_u - old_u)
                    if added:
                        pl.problems.append(
                            f"uses name(s) nothing defines: {', '.join(added[:8])} (NameError at run "
                            f"time - usually a missing import). --skip-checks to override")
            if py:
                changed = {rel: (pl.old_text, pl.new_text or "") for rel, pl in py.items()}
                for rel, probs in cross_file_problems(changed, self.index, self._read_current_text).items():
                    for pr in probs:
                        py[rel].problems.append(pr + ". --skip-checks to override")
        return plans

    def _plan_one(self, prop: Proposal) -> Plan:
        pl = Plan(proposal=prop)
        pl.notes.extend(prop.notes)
        try:
            rel = normalize_rel(prop.raw_path, self.root)
        except PathRefused as exc:
            pl.problems.append(f"path refused: {exc}")
            return pl
        raw_parts = [x for x in prop.raw_path.strip().strip("`'\"*").replace("\\", "/").split("/")
                     if x not in ("", ".")]
        if len(raw_parts) > rel.count("/") + 1:
            pl.notes.append(f"leading '{raw_parts[0]}/' removed (the repo name, as the dump labels paths)")
        if is_protected_rel(rel):
            pl.problems.append("refused: protected path (.git / venv / .env / tooling / retired files / dev_data)")
            return pl
        rel = canonical_case(self.root, rel)
        try:
            target = safe_target(self.root, rel)
        except PathRefused as exc:
            pl.problems.append(f"path refused: {exc}")
            return pl

        exists = target.exists()
        if exists and not target.is_file():
            pl.problems.append("target exists and is not a regular file")
            return pl

        # An EDIT for a path that does not exist may carry a dropped prefix
        # ('src/auto_apply/x.py'). Accept ONLY a unique, component-aligned
        # suffix match - and even then every anchor must still match there.
        if prop.kind == "edit" and not exists:
            hits = self.index.suffix_matches(rel) if "/" in rel else []
            how = "unique path-suffix match"
            if len(hits) != 1:
                # The suffix rule recovers a DROPPED PREFIX only. A model that
                # guessed a wrong MIDDLE directory - tests/pins/x.py for a file
                # in tests/architecture/ - matches no suffix, and that threw
                # away a whole good batch once. Fall back to a unique basename.
                # Safe for the same reason: a repathed edit still goes through
                # _plan_edit, so every SEARCH must resolve in the candidate or
                # the batch is rejected. The content is the proof, not the name.
                # basename_matches is a superset of suffix_matches, so an
                # ambiguous suffix can never become a unique basename here.
                hits = self.index.basename_matches(rel.rsplit("/", 1)[-1])
                how = "unique basename match"
            if len(hits) == 1:
                pl.notes.append(f"path corrected: {rel} -> {hits[0]} ({how}; every SEARCH "
                                f"must still match there)")
                rel = hits[0]
                target = safe_target(self.root, rel)
                exists = target.exists()
            else:
                others = self.index.basename_matches(rel.rsplit("/", 1)[-1])
                tip = f" Files with that name: {', '.join(others[:4])}" if others else ""
                pl.problems.append(f"EDIT target does not exist: {rel}.{tip} (if this file was "
                                   f"created earlier in the conversation and not applied yet, send "
                                   f"it again as one complete FILE)")
                pl.rel, pl.target = rel, target
                return pl

        pl.rel, pl.target = rel, target
        if exists:
            pl.old_bytes = target.read_bytes()
            if not os.access(str(target), os.W_OK):
                pl.problems.append("file is read-only on disk")
        if prop.kind == "edit":
            self._plan_edit(pl)
        else:
            self._plan_file(pl)
        if pl.new_text is not None and not pl.problems and pl.action != "identical":
            err = validate_syntax(rel, pl.new_text)
            if err:
                pl.problems.append(err)
        return pl

    def _plan_edit(self, pl: Plan) -> None:
        prop = pl.proposal
        assert pl.old_bytes is not None
        try:
            text, bom = decode_strict(pl.old_bytes)
        except NotText as exc:
            pl.problems.append(f"cannot edit: file {exc}")
            return
        pl.old_text = text
        cur_sha = sha256_bytes(pl.old_bytes)
        if prop.after_sha and cur_sha == prop.after_sha:
            pl.action, pl.new_bytes, pl.new_text = "identical", pl.old_bytes, text
            pl.notes.append("already applied (file matches the staged result exactly)")
            return
        if prop.base_sha and cur_sha != prop.base_sha:
            pl.notes.append("file changed since this reply was staged - every edit re-anchored "
                            "against the file as it is now")
        for ed in prop.edits:
            for pat in ELISION:
                m = pat.search(ed.replace)
                if m and not pat.search(ed.search):
                    pl.problems.append(
                        f"edit #{prop.edits.index(ed) + 1}: REPLACE contains a placeholder "
                        f"{m.group(0).strip()[:50]!r} - it would replace real code with a comment")
                    break
        new_text, outcomes = apply_edits(text, prop.edits)
        pl.outcomes = outcomes
        failed = [o for o in outcomes if o.status == "failed"]
        for o in failed:
            pl.problems.append(f"edit #{o.index} (reply line {o.reply_line}): {o.problem}")
        if failed:
            return
        have = [o for o in outcomes if o.status == "have"]
        for o in outcomes:
            if o.how and o.how != "exact":
                pl.notes.append(f"edit #{o.index}: {o.how}")
        if have and len(have) < len(outcomes):
            pl.notes.append(f"HALF-APPLIED before this run: {len(have)} of {len(outcomes)} edits "
                            f"were already present; applying the rest")
        pl.new_text = new_text
        pl.new_bytes = encode_text(new_text, bom)
        pl.action = "identical" if pl.new_bytes == pl.old_bytes else "update"

    def _plan_file(self, pl: Plan) -> None:
        prop = pl.proposal
        content = (prop.content or "").replace("\r\n", "\n")
        if not content.strip():
            pl.problems.append("empty content")
            return
        rel = pl.rel or ""
        if pl.old_bytes is not None:
            try:
                old_text, bom = decode_strict(pl.old_bytes)
            except NotText as exc:
                pl.problems.append(f"refusing to overwrite: existing file {exc}")
                return
            pl.old_text = old_text
            eol = dominant_eol(old_text)
            new_text = content.replace("\n", eol) if eol == "\r\n" else content
            pl.new_text = new_text
            pl.new_bytes = encode_text(new_text, bom)
            if normalise_for_compare(old_text) == normalise_for_compare(content):
                pl.action = "identical"
                pl.new_bytes, pl.new_text = pl.old_bytes, old_text
                return
            pl.action = "update"
            cur_sha = sha256_bytes(pl.old_bytes)
            if prop.base_sha == "":
                msg = ("this file did NOT exist when the reply was staged, but exists now - "
                       "writing would overwrite a file Kimi never saw")
                (pl.notes if self.opt.allow_stale else pl.problems).append(
                    msg + ("" if self.opt.allow_stale else ". --allow-stale to override"))
            if prop.base_sha is not None and prop.base_sha and cur_sha != prop.base_sha:
                msg = ("file changed on disk AFTER this reply was staged; writing the whole file "
                       "would silently revert that change")
                (pl.notes if self.opt.allow_stale else pl.problems).append(
                    msg + ("" if self.opt.allow_stale else ". Ask for EDIT blocks, or --allow-stale"))
            if prop.known_bases:
                cmp_old = normalise_for_compare(old_text)
                if not any(normalise_for_compare(b) == cmp_old for b in prop.known_bases):
                    base = prop.known_bases[0]
                    nchg = sum(1 for ln in difflib.unified_diff(
                        normalise_for_compare(base).split("\n"), cmp_old.split("\n"), n=0)
                        if ln[:1] in "+-" and not ln.startswith(("+++", "---")))
                    msg = (f"STALE BASE: your file differs from the version Kimi was shown "
                           f"(~{nchg} changed lines). A whole-file write would revert them")
                    (pl.notes if self.opt.allow_stale else pl.problems).append(
                        msg + ("" if self.opt.allow_stale else " - ask for EDIT blocks, or --allow-stale"))
            old_lines = old_text.count("\n") + 1
            new_lines = content.count("\n") + 1
            if (not self.opt.allow_shrink and old_lines > 40
                    and new_lines < old_lines * self.opt.shrink_ratio):
                pl.problems.append(
                    f"content shrank {old_lines} -> {new_lines} lines (< {int(self.opt.shrink_ratio * 100)}%); "
                    f"looks truncated. --allow-shrink to override")
            for pat in ELISION:
                m = pat.search(content)
                if m and not pat.search(old_text):
                    line = content[:m.start()].count("\n") + 1
                    pl.problems.append(f"placeholder at line {line}: {m.group(0).strip()[:60]!r} - "
                                       f"this is a summary, not a whole file")
                    break
            return

        # ---- create ----
        pl.action = "create"
        if not self.opt.allow_new_files:
            pl.problems.append("new file; --allow-new-files to permit")
        mis = self.index.suffix_matches(rel) if "/" in rel else self.index.basename_matches(rel)
        mis = [m for m in mis if m.casefold() != rel.casefold()]
        if mis and ("/" in rel or len(mis) == 1):
            pl.problems.append(
                f"looks mis-pathed: {mis[0]} already exists and ends with this path. Creating "
                f"{rel} would add a DUPLICATE. Re-emit with the exact path")
        else:
            same_name = [m for m in self.index.basename_matches(rel.rsplit("/", 1)[-1])
                         if m.casefold() != rel.casefold()]
            if same_name:
                pl.notes.append(f"a file with this name also exists at {', '.join(same_name[:3])}")
        parent_parts = rel.split("/")[:-1]
        missing: List[str] = []
        for k in range(1, len(parent_parts) + 1):
            d = "/".join(parent_parts[:k])
            if not (self.root / d).is_dir():
                if (self.root / d).exists():
                    pl.problems.append(f"{d} exists but is not a directory")
                    return
                missing.append(d)
        if missing:
            pl.dirs_to_create = missing
            if not self.opt.allow_new_dirs:
                pl.problems.append(f"would create new director{'y' if len(missing) == 1 else 'ies'} "
                                   f"{missing[-1]}/ - often a mis-pathed file. --allow-new-dirs to permit")
            else:
                pl.notes.append(f"creates director{'y' if len(missing) == 1 else 'ies'}: {', '.join(missing)}")
        for pat in ELISION:
            m = pat.search(content)
            if m:
                line = content[:m.start()].count("\n") + 1
                pl.problems.append(f"placeholder at line {line}: {m.group(0).strip()[:60]!r}")
                break
        if not missing:
            parent = self.root.joinpath(*parent_parts) if parent_parts else self.root
            try:
                siblings = [s for s in parent.iterdir() if s.is_file() and s.suffix == Path(rel).suffix]
            except OSError:
                siblings = []
            for s in siblings[:60]:
                try:
                    other = s.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if len(other) > 400 and difflib.SequenceMatcher(None, other, content, autojunk=False).quick_ratio() > 0.9:
                    if difflib.SequenceMatcher(None, other, content, autojunk=False).ratio() > 0.85:
                        pl.notes.append(f"content is >85% the same as existing {s.name} - a copy "
                                        f"under a new name?")
                        break
        eol = gitattributes_eol(self.root, rel)
        pl.new_text = content.replace("\n", eol) if eol == "\r\n" else content
        pl.new_bytes = encode_text(pl.new_text, False)

    # -- previews -----------------------------------------------------
    def write_preview(self, plans: List[Plan], dest: Path) -> int:
        chunks: List[str] = []
        for pl in plans:
            if not pl.changes:
                continue
            old = (pl.old_text or "").replace("\r\n", "\n").splitlines(keepends=True)
            new = (pl.new_text or "").replace("\r\n", "\n").splitlines(keepends=True)
            a = f"a/{pl.rel}" if pl.action != "create" else "/dev/null"
            chunks.extend(difflib.unified_diff(old, new, a, f"b/{pl.rel}", n=3))
            if chunks and not chunks[-1].endswith("\n"):
                chunks.append("\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("".join(chunks) or "(no changes)\n", encoding="utf-8", newline="\n")
        return sum(1 for c in chunks if c.startswith(("+", "-")) and not c.startswith(("+++", "---")))

    # -- pass 2 -------------------------------------------------------
    def apply(self, plans: List[Plan], meta: Dict[str, Any],
              _write: Any = None) -> Dict[str, Any]:
        """Write every changed plan, or none. Order of operations is the
        whole guarantee:
          1. re-read each target; abort if it moved since pass 1
          2. back up every original, then re-read the backup and verify it
          3. write the manifest (status=writing) BEFORE touching the repo
          4. write each file atomically, then re-read and verify it
          5. any failure -> restore everything already written, verified
        """
        write = _write or write_bytes_atomic
        todo = [p for p in plans if p.changes]
        if any(p.problems for p in plans):
            raise ApplyAborted("refusing to write: pass 1 reported problems")
        seq = time.time_ns()
        mid = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        backup_root = self.backup_dir / mid
        manifest_path = self.backup_dir / f"manifest_{mid}.json"

        for p in todo:                                       # 1
            assert p.target is not None
            now = read_bytes_or_none(p.target)
            if now != p.old_bytes:
                raise ApplyAborted(f"{p.rel} changed while kimicli was running - nothing written; "
                                   f"run the command again")

        entries: List[Dict[str, Any]] = []
        for p in todo:                                       # 2
            assert p.rel is not None and p.new_bytes is not None
            entry: Dict[str, Any] = {
                "path": p.rel, "action": p.action,
                "before_sha": sha256_bytes(p.old_bytes) if p.old_bytes is not None else None,
                "after_sha": sha256_bytes(p.new_bytes),
                "backup": None, "created_dirs": list(p.dirs_to_create),
                "source": p.proposal.source,
            }
            if p.old_bytes is not None:
                dest = backup_root / "files" / p.rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                write_bytes_atomic(dest, p.old_bytes)
                if sha256_bytes(dest.read_bytes()) != entry["before_sha"]:
                    raise ApplyAborted(f"backup of {p.rel} did not verify - nothing written")
                entry["backup"] = (Path(mid) / "files" / p.rel).as_posix()
            entries.append(entry)

        manifest: Dict[str, Any] = {                         # 3
            "version": MANIFEST_VERSION, "id": mid, "seq": seq,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "root": str(self.root), "status": "writing", **meta,
            "git": git_snapshot(self.root, mid),
            "entries": entries,
        }
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(manifest_path, json.dumps(manifest, indent=2).encode("utf-8"))

        done: List[Tuple[Plan, Dict[str, Any]]] = []
        try:                                                 # 4
            for p, entry in zip(todo, entries):
                assert p.target is not None and p.new_bytes is not None
                for d in p.dirs_to_create:
                    (self.root / d).mkdir(exist_ok=True)
                done.append((p, entry))
                write(p.target, p.new_bytes, p.target if p.action == "update" else None)
                if sha256_bytes(p.target.read_bytes()) != entry["after_sha"]:
                    raise ApplyAborted(f"{p.rel} did not read back as written")
        except BaseException as exc:                         # 5
            report = self._rollback(done, backup_root)
            manifest["status"] = "rolled_back" if not report else "rollback_incomplete"
            manifest["error"] = f"{type(exc).__name__}: {exc}"
            manifest["rollback_problems"] = report
            write_bytes_atomic(manifest_path, json.dumps(manifest, indent=2).encode("utf-8"))
            if report:
                raise ApplyAborted(
                    f"write failed ({exc}) and the automatic rollback could not restore: "
                    f"{'; '.join(report)}. Backups are in {backup_root}"
                    + (f"; git snapshot {manifest['git'].get('snapshot')}" if manifest.get("git") else ""))
            raise ApplyAborted(f"write failed ({type(exc).__name__}: {exc}); every file was restored "
                               f"to its original bytes and verified. Nothing changed.") from exc

        manifest["status"] = "complete"
        manifest["completed"] = time.strftime("%Y-%m-%d %H:%M:%S")
        write_bytes_atomic(manifest_path, json.dumps(manifest, indent=2).encode("utf-8"))
        return manifest

    def _rollback(self, done: List[Tuple[Plan, Dict[str, Any]]], backup_root: Path) -> List[str]:
        problems: List[str] = []
        for p, entry in reversed(done):
            assert p.target is not None
            try:
                cur = read_bytes_or_none(p.target)
                cur_sha = sha256_bytes(cur) if cur is not None else None
                if entry["action"] == "create":
                    if cur is not None and cur_sha == entry["after_sha"]:
                        _unlink_with_retry(p.target)
                    elif cur is not None:
                        problems.append(f"{p.rel}: unexpected content, left in place")
                    for d in reversed(entry["created_dirs"]):
                        try:
                            (self.root / d).rmdir()
                        except OSError:
                            pass
                else:
                    if cur_sha != entry["before_sha"]:
                        write_bytes_atomic(p.target, p.old_bytes or b"", p.target)
                    if sha256_bytes(p.target.read_bytes()) != entry["before_sha"]:
                        problems.append(f"{p.rel}: restore did not verify")
            except Exception as exc:
                problems.append(f"{p.rel}: {exc}")
        return problems


# ==========================================================================
# Manifests: history and a verified, all-or-nothing, idempotent undo
# ==========================================================================

def _load_manifest(path: Path) -> Optional[Dict[str, Any]]:
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if "entries" not in m:                    # v2 manifest from the old kimicli
        if m.get("dry_run"):
            return None
        m["legacy"] = True
        m.setdefault("status", "complete")
        m["entries"] = [{
            "path": f["path"], "action": f.get("action", "update"),
            "before_sha": f.get("sha256_before"), "after_sha": f.get("sha256_after"),
            "backup": f.get("backup"), "created_dirs": [],
        } for f in m.get("files", []) if f.get("action") != "identical"]
    m["_path"] = str(path)
    return m


def list_manifests(backup_dir: Path) -> List[Dict[str, Any]]:
    out = []
    if backup_dir.exists():
        for p in backup_dir.glob("manifest_*.json"):
            m = _load_manifest(p)
            if m:
                out.append(m)
    out.sort(key=_manifest_order)
    return out


def _manifest_order(m: Dict[str, Any]) -> Tuple[int, str]:
    """Newest-last. 'seq' (nanoseconds) orders two applies made in the same
    second; the old v2 manifests only have a to-the-second 'created'."""
    if isinstance(m.get("seq"), int):
        return (m["seq"], str(m.get("id", "")))
    try:
        ts = int(time.mktime(time.strptime(str(m.get("created")), "%Y-%m-%d %H:%M:%S")) * 1_000_000_000)
    except (ValueError, OverflowError):
        ts = 0
    return (ts, str(m.get("id", "")))


def _state(cur: Optional[bytes], sha: Optional[str], legacy: bool) -> bool:
    if cur is None or not sha:
        return False
    if sha256_bytes(cur) == sha:
        return True
    # the v2 kimicli hashed LF text but wrote CRLF files, so its after-hash
    # never matched a CRLF file's bytes; accept that one known variant
    return legacy and sha256_bytes(cur.replace(b"\r\n", b"\n")) == sha


def undo(root: Path, backup_dir: Path, token: str, force: bool = False, assume_yes: bool = False) -> int:
    manifests = list_manifests(backup_dir)
    if token == "last":
        live = [m for m in manifests if m.get("status") in ("complete", "writing", "rollback_incomplete")]
        if not live:
            print("Nothing to undo: no applied change set that has not already been undone.")
            return 1
        m = live[-1]
    else:
        match = [m for m in manifests if m.get("id") == token]
        if not match:
            ids = ", ".join(str(x.get("id")) for x in manifests[-8:]) or "(none)"
            print(f"No manifest '{token}'. Recent: {ids}")
            return 1
        m = match[0]
    if m.get("status") == "undone":
        print(f"{m['id']} was already undone at {m.get('undone_at')}.")
        return 0
    if m.get("status") == "rolled_back":
        print(f"{m['id']} was rolled back automatically when it failed; nothing to undo.")
        return 0

    try:
        same_root = Path(str(m.get("root", root))).resolve() == root.resolve()
    except OSError:
        same_root = False
    if not same_root and not force:
        print(f"Manifest {m['id']} was written for {m.get('root')}, not {root}. Refusing "
              f"(--force to override).")
        return 1

    legacy = bool(m.get("legacy"))
    plan: List[Tuple[str, Dict[str, Any], Optional[bytes], Optional[bytes]]] = []
    blocked: List[str] = []
    for e in m["entries"]:
        target = root.joinpath(*e["path"].split("/"))
        cur = read_bytes_or_none(target)
        if e["action"] == "create":
            if cur is None:
                plan.append(("have", e, cur, None))
            elif _state(cur, e["after_sha"], legacy):
                plan.append(("delete", e, cur, None))
            else:
                (plan.append(("delete-forced", e, cur, None)) if force
                 else blocked.append(f"{e['path']}: edited since kimicli created it"))
            continue
        bk = backup_dir.joinpath(*e["backup"].split("/")) if e.get("backup") else None
        orig = read_bytes_or_none(bk) if bk else None
        if orig is None or (e.get("before_sha") and sha256_bytes(orig) != e["before_sha"]):
            blocked.append(f"{e['path']}: backup missing or damaged - use the git snapshot "
                           f"{(m.get('git') or {}).get('snapshot', '(none)')}")
            continue
        if cur is not None and sha256_bytes(cur) == sha256_bytes(orig):
            plan.append(("have", e, cur, orig))
        elif _state(cur, e["after_sha"], legacy):
            plan.append(("restore", e, cur, orig))
        elif force:
            plan.append(("restore-forced", e, cur, orig))
        else:
            blocked.append(f"{e['path']}: changed since the apply (your edits, or a later apply)")

    print(f"\nUndo {m['id']}  (applied {m.get('created')}, status {m.get('status')})")
    for kind, e, _, _ in plan:
        label = {"have": "[have]  ", "restore": "restore ", "delete": "delete  ",
                 "restore-forced": "RESTORE!", "delete-forced": "DELETE! "}[kind]
        print(f"  {label} {e['path']}")
    if blocked:
        print("\nREFUSED - undo is all-or-nothing, and these files cannot be restored safely:")
        for b in blocked:
            print(f"  !! {b}")
        print("\nNothing was changed. If the changes listed are ones you are happy to lose, "
              "run again with --force:\nevery file it overwrites or removes is saved first, "
              "so even --force loses nothing.")
        return 1
    work = [x for x in plan if x[0] != "have"]
    if not work:
        _mark_undone(m, backup_dir)
        print("  already fully undone - nothing to do.")
        return 0
    if not assume_yes and not confirm("Proceed?"):
        print("Cancelled. Nothing was changed.")
        return 1

    # Save what is there NOW before replacing it - undo can itself be undone
    # by hand, and --force never destroys anything.
    stamp = time.strftime("%Y%m%d_%H%M%S")
    saved = backup_dir / m["id"] / f"undo_{stamp}"
    for _kind, e, cur, _ in work:
        if cur is not None:
            dest = saved / e["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(dest, cur)
    failures: List[str] = []
    for kind, e, _cur, orig in work:
        target = root.joinpath(*e["path"].split("/"))
        try:
            if kind.startswith("delete"):
                _unlink_with_retry(target)
                for d in reversed(e.get("created_dirs") or []):
                    try:
                        (root / d).rmdir()
                    except OSError:
                        pass
                if target.exists():
                    failures.append(f"{e['path']}: still present")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                write_bytes_atomic(target, orig or b"", target if target.exists() else None)
                if sha256_bytes(target.read_bytes()) != sha256_bytes(orig or b""):
                    failures.append(f"{e['path']}: restore did not verify")
        except Exception as exc:
            failures.append(f"{e['path']}: {exc}")
    if failures:
        print("\n!! Undo hit problems (run the same --undo again; finished files are skipped):")
        for f in failures:
            print(f"  !! {f}")
        return 1
    _mark_undone(m, backup_dir, str(saved))
    print(f"\nUndo complete - every file verified byte-for-byte against its backup."
          f"\n(What was there before the undo is saved in {saved})")
    return 0


def _mark_undone(m: Dict[str, Any], backup_dir: Path, saved: str = "") -> None:
    path = Path(m["_path"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    raw["status"] = "undone"
    raw["undone_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if saved:
        raw["undo_saved"] = saved
    write_bytes_atomic(path, json.dumps(raw, indent=2).encode("utf-8"))


def print_history(backup_dir: Path, limit: int = 15) -> None:
    ms = list_manifests(backup_dir)
    if not ms:
        print("No applies recorded yet.")
        return
    print(f"\n  {'id':<24} {'applied':<20} {'status':<20} files  source")
    for m in ms[-limit:]:
        n = len(m.get("entries", []))
        src = m.get("source", "legacy v2" if m.get("legacy") else "")
        print(f"  {str(m.get('id')):<24} {str(m.get('created')):<20} {str(m.get('status')):<20} "
              f"{n:>5}  {src}")
    print("\n  Undo the newest live one:  python kimicli.py --undo last\n")


# ==========================================================================
# Repair prompts: turn every failure into a cheap, exact follow-up turn
# ==========================================================================

def build_repair_prompt(plans: List[Plan], parse_problems: List[ParseProblem], turn: Optional[int]) -> str:
    lines = [
        "REPAIR REQUEST - your last change set could not be applied, so NOTHING was written.",
        "",
        "Re-emit the change blocks for the files listed below and ONLY those files. For each one,",
        "re-emit ALL of its blocks (not just the failed one): the latest emission for a file",
        "replaces every earlier one. Files not listed here are fine - do not re-emit them.",
        "Copy every SEARCH character-for-character from the CURRENT text shown here, not from",
        "the codebase dump (the file may have changed since the dump was made).",
        "Finish with the line ### END CHANGES.",
        "",
    ]
    n = 0
    for pp in parse_problems:
        if pp.severity != "error":
            continue
        n += 1
        where = f" ({pp.path})" if pp.path else ""
        lines.append(f"{n}. Reply line {pp.line}{where}: {pp.message}")
    for pl in plans:
        if not pl.problems:
            continue
        n += 1
        lines.append(f"{n}. {pl.rel or pl.proposal.raw_path}:")
        for pr in pl.problems:
            lines.append(f"   - {pr}")
        for o in pl.outcomes:
            if o.status == "failed" and o.diag:
                lines.append(f"   Current text of the closest region to edit #{o.index}'s SEARCH "
                             f"({int(o.diag['ratio'] * 100)}% similar) - line numbers are for "
                             f"reference only, do not copy them:")
                lines.append("   ```")
                lines.extend("   " + x for x in o.diag["excerpt"].split("\n"))
                lines.append("   ```")
        lines.append("")
    if n == 0:
        return ""
    return "\n".join(lines).rstrip() + "\n"


# ==========================================================================
# Staging a reply: parse -> group per file -> trial-resolve against the live
# tree -> record -> preview diff -> repair prompt when anything is wrong
# ==========================================================================

REPAIR_TAG_RE = re.compile(r"\[kimicli-repair-of-turn:\s*(\d+)\]")


@dataclass
class Group:
    key: str                      # casefolded normalised path (or raw, if unnormalisable)
    raw_path: str
    kind: str                     # "file" | "edit"
    line: int
    edits: List[EditBlock] = field(default_factory=list)
    content: Optional[str] = None
    style: str = "header"


def group_blocks(pr: ParseResult, root: Path) -> Tuple[List[Group], List[ParseProblem]]:
    """One Group per file, in first-seen order. Several EDIT blocks for one
    file merge in emission order; a FILE twice, or FILE and EDIT mixed for the
    same file, is an error rather than a guess."""
    groups: Dict[str, Group] = {}
    order: List[str] = []
    problems: List[ParseProblem] = []
    for b in pr.blocks:
        try:
            key = normalize_rel(b.path, root).casefold()
        except PathRefused as exc:
            problems.append(ParseProblem(b.line, f"path refused: {exc}", path=b.path))
            key = b.path.strip().casefold()
        g = groups.get(key)
        if g is None:
            g = Group(key=key, raw_path=b.path, kind=b.kind, line=b.line, style=b.style)
            groups[key] = g
            order.append(key)
        elif g.kind != b.kind:
            problems.append(ParseProblem(b.line, f"{b.path} is sent both as FILE and as EDIT in one "
                                                 f"reply - send one or the other", path=b.path))
            continue
        elif b.kind == "file":
            problems.append(ParseProblem(b.line, f"{b.path} is sent as a whole FILE twice in one "
                                                 f"reply", path=b.path))
            continue
        if b.kind == "edit" and b.edit is not None:
            g.edits.append(b.edit)
        else:
            g.content = b.content
    return [groups[k] for k in order], problems


def announcement_problems(pr: ParseResult, groups: List[Group], root: Path) -> List[ParseProblem]:
    """The contract makes Kimi list every file before the first block. A file
    announced but never emitted is the signature of an omission or a cut-off
    reply - the half-applied change this tool exists to prevent."""
    out: List[ParseProblem] = []
    emitted = [g.key for g in groups]
    for line, path, kind in pr.announced:
        try:
            key = normalize_rel(path, root).casefold()
        except PathRefused:
            continue
        if not any(e == key or e.endswith("/" + key) or key.endswith("/" + e) for e in emitted):
            out.append(ParseProblem(line, f"{path} was announced as {kind.upper()} but no block for "
                                          f"it appears in the reply", path=path))
    return out


def codebase_versions(messages: List[Dict[str, Any]], root: Path) -> Dict[str, str]:
    """casefolded rel path -> that file's text as the model was shown it in
    the codebase dump. Empty if the dump format is not recognised."""
    for m in messages:
        c = m.get("content")
        if m.get("role") == "system" and isinstance(c, str) and c.startswith("<codebase"):
            body = c.split("\n", 1)[1] if "\n" in c else ""
            if body.endswith("</codebase>"):
                body = body[: -len("</codebase>")]
            hits = list(SECTION_PATTERNS[0].finditer(body))
            out: Dict[str, str] = {}
            for i, h in enumerate(hits):
                end = hits[i + 1].start() if i + 1 < len(hits) else len(body)
                text = body[h.end():end]
                if text.startswith("\n"):
                    text = text[1:]
                try:
                    out[normalize_rel(h.group("path"), root).casefold()] = text
                except PathRefused:
                    continue
            return out
    return {}


def attachment_versions(messages: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """basename (casefolded) -> texts of attachments with that name."""
    out: Dict[str, List[str]] = {}
    for m in messages:
        c = m.get("content")
        if m.get("role") != "user" or not isinstance(c, str) or "<attachment" not in c:
            continue
        for a in re.finditer(r'<attachment name="([^"]+)">\n(.*?)\n</attachment>', c, re.S):
            out.setdefault(a.group(1).casefold(), []).append(a.group(2))
    return out


def _proposal_from_group(g: Group, source: str, root: Path) -> Proposal:
    return Proposal(raw_path=g.raw_path, kind=g.kind, content=g.content,
                    edits=list(g.edits), source=source)


@dataclass
class StageSummary:
    turn: int
    parse: ParseResult
    group_problems: List[ParseProblem]
    plans: List[Plan]
    repair_path: Optional[Path] = None
    preview_path: Optional[Path] = None
    changed_lines: int = 0


def stage_turn(session: "Session", turn: int, reply: str, finish_reason: Optional[str]) -> StageSummary:
    session.save_reply(turn, reply)
    pr = parse_changes(reply)
    if pr.blocks and not pr.end_marker:
        cut = finish_reason in ("length", "error", "interrupted")
        pr.problems.append(ParseProblem(
            0, ("the reply ENDED EARLY (finish_reason=" + str(finish_reason) + ") and never "
                "reached '### END CHANGES' - blocks after the cut are missing") if cut else
               "no '### END CHANGES' line after the last block - if the reply was cut short, a "
               "file may be missing", severity="error" if cut else "warning"))
    groups, gprobs = group_blocks(pr, PROJECT_ROOT)
    gprobs += announcement_problems(pr, groups, PROJECT_ROOT)

    last_user = next((m for m in reversed(session.messages) if m.get("role") == "user"), None)
    repairs = None
    if last_user and isinstance(last_user.get("content"), str):
        mt = REPAIR_TAG_RE.search(last_user["content"])
        repairs = int(mt.group(1)) if mt else None

    dump = codebase_versions(session.messages, PROJECT_ROOT)
    attach = attachment_versions(session.messages)
    earlier: Dict[str, List[str]] = {}             # key -> earlier FILE texts in this session
    for row in session.rows():
        if row.get("kind", "file") == "file" and row.get("turn", 0) < turn:
            k = row.get("key") or row["path"].casefold()
            txt = session.read_artifact(row)
            if isinstance(txt, str):
                earlier.setdefault(k, []).append(txt)

    proposals: List[Proposal] = []
    for g in groups:
        prop = _proposal_from_group(g, f"turn {turn}", PROJECT_ROOT)
        try:
            rel = normalize_rel(g.raw_path, PROJECT_ROOT)
            disk = read_bytes_or_none(PROJECT_ROOT.joinpath(*rel.split("/")))
            prop.base_sha = sha256_bytes(disk) if disk is not None else ""
            if g.kind == "file" and disk is not None:
                bases = []
                if g.key in dump:
                    bases.append(dump[g.key])
                bases += attach.get(rel.rsplit("/", 1)[-1].casefold(), [])
                bases += earlier.get(g.key, [])
                prop.known_bases = bases
        except PathRefused:
            pass
        proposals.append(prop)

    trial = Applier(PROJECT_ROOT, BACKUP_DIR,
                    ApplyOptions(allow_new_files=True, allow_new_dirs=True))
    plans = trial.validate(proposals) if proposals else []

    rows = []
    for g, prop, pl in zip(groups, proposals, plans):
        staged = (session.stage_edits(g.raw_path, g.edits, turn) if g.kind == "edit"
                  else session.stage(g.raw_path, g.content or "", turn))
        rows.append({
            "turn": turn, "kind": g.kind, "path": g.raw_path, "key": g.key,
            "blocks": len(g.edits) if g.kind == "edit" else 1,
            "staged": staged.relative_to(session.dir).as_posix(),
            "sha256": sha256_bytes(staged.read_bytes()),
            "base_sha": prop.base_sha,
            "after_sha": sha256_bytes(pl.new_bytes) if (pl.new_bytes is not None and not pl.problems) else None,
            "known_bases": len(prop.known_bases),
            "trial": "ok" if not pl.problems else "problem",
        })
    if rows:
        session.append_rows(rows)

    all_parse = pr.problems + gprobs
    session.write_parse_report(turn, {
        "turn": turn, "finish_reason": finish_reason, "repairs": repairs,
        "end_marker": pr.end_marker, "blocks": len(pr.blocks), "files": len(groups),
        "blocks_after_end": pr.blocks_after_end,
        "problems": [{"line": p.line, "message": p.message, "severity": p.severity,
                      "key": _key_or_none(p.path)} for p in all_parse],
    })

    summary = StageSummary(turn=turn, parse=pr, group_problems=gprobs, plans=plans)
    if plans:
        summary.preview_path = session.dir / f"preview_turn{turn}.diff"
        summary.changed_lines = trial.write_preview(plans, summary.preview_path)
    errors = [p for p in all_parse if p.severity == "error"]
    if errors or any(pl.problems for pl in plans):
        body = build_repair_prompt([pl for pl in plans if pl.problems], errors, turn)
        if body:
            summary.repair_path = session.dir / f"repair_turn{turn}.md"
            atomic_write(summary.repair_path, body + f"\n[kimicli-repair-of-turn: {turn}]\n")
    return summary


def _key_or_none(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        return normalize_rel(path, PROJECT_ROOT).casefold()
    except PathRefused:
        return path.strip().casefold()


def _rel_display(p: Path) -> str:
    """Relative when you are standing in the project root (the usual case),
    absolute otherwise - a --prompt path that does not resolve is sent as
    literal text, which once cost a full call."""
    try:
        if Path.cwd().resolve() == PROJECT_ROOT.resolve():
            return str(p.resolve().relative_to(PROJECT_ROOT.resolve()))
    except (ValueError, OSError):
        pass
    return str(p.resolve())


def print_stage_summary(s: StageSummary, session: "Session") -> None:
    """Printed LAST, after the usage summary, so it is the final thing on screen."""
    pr = s.parse
    n_edit = sum(1 for b in pr.blocks if b.kind == "edit")
    n_file = sum(1 for b in pr.blocks if b.kind == "file")
    files = len(s.plans)
    errors = [p for p in pr.problems + s.group_problems if p.severity == "error"]
    warnings = [p for p in pr.problems + s.group_problems if p.severity != "error"]
    if not pr.blocks and not errors and not warnings:
        return
    print("\n" + "=" * 70)
    print(f"CHANGES IN TURN {s.turn}: {n_edit} EDIT block(s) + {n_file} FILE block(s) across "
          f"{files} file(s)   END marker: {'yes' if pr.end_marker else 'NO'}")
    for pl in s.plans:
        kind = pl.proposal.kind.upper()
        if pl.problems:
            state = "FAIL"
        elif pl.action == "identical":
            state = "same"
        else:
            state = "NEW " if pl.action == "create" else "ok  "
        detail = ""
        if pl.proposal.kind == "edit" and pl.outcomes:
            ok = sum(1 for o in pl.outcomes if o.status == "applied")
            detail = f"{ok}/{len(pl.outcomes)} edits resolve"
        elif pl.new_text is not None:
            detail = f"{pl.new_text.count(chr(10)) + 1} lines"
        print(f"  [{state}] {kind:<4} {pl.rel or pl.proposal.raw_path}   {detail}")
        for note in pl.notes:
            print(f"           note: {note}")
        for prob in pl.problems:
            print(f"           !! {prob}")
    for p in warnings:
        print(f"  warning (reply line {p.line}): {p.message}")
    for p in errors:
        print(f"  !! (reply line {p.line}): {p.message}")
    if s.preview_path:
        print(f"\n  preview diff: {_rel_display(s.preview_path)}   ({s.changed_lines} changed lines)")
    news = [pl for pl in s.plans if pl.action == "create" and not pl.problems]
    if s.repair_path:
        print("\n  NOT APPLICABLE AS-IS. Nothing will be written until this is fixed.")
        print("  Send the ready-made repair NOW, while the cache is warm (a resume within minutes")
        print("  is ~95% cached):")
        print(f"\n    python kimicli.py --resume {session.id} --prompt "
              f"{_rel_display(s.repair_path)} --request-code")
    elif s.plans and any(pl.changes for pl in s.plans):
        flag = " --allow-new-files" if news else ""
        if any(pl.dirs_to_create for pl in news):
            flag += " --allow-new-dirs"
        print("\n  Every block resolves against your tree right now. Next:")
        print(f"\n    python kimicli.py --apply-fixes {session.id} --dry-run{flag}")
    elif s.plans:
        print("\n  Every file already matches these blocks - nothing to apply.")
    print("=" * 70)
    session.printed_stage_summary = True


# ==========================================================================
# Loading what to apply from a session (or a saved reply file)
# ==========================================================================

def load_session_proposals(session: "Session", turns: Optional[Sequence[int]] = None,
                           skips: Optional[Sequence[str]] = None
                           ) -> Tuple[List[Proposal], List[str], List[str]]:
    """Latest emission per file across the chosen turns.
    Returns (proposals, blocking problems, info lines)."""
    rows = session.rows()
    info: List[str] = []
    blocking: List[str] = []
    if turns:
        rows = [r for r in rows if int(r.get("turn", 0)) in set(turns)]
    skip_keys = set()
    for sp in skips or []:
        k = _key_or_none(sp)
        if k:
            skip_keys.add(k)
    chosen: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for r in rows:
        k = r.get("key") or _key_or_none(r["path"]) or r["path"]
        r["key"] = k
        if k in skip_keys:
            continue
        if k not in chosen:
            order.append(k)
        prev = chosen.get(k)
        if prev is None or int(r.get("turn", 0)) >= int(prev.get("turn", 0)):
            chosen[k] = r

    # Parse problems block unless a later chosen emission supersedes them.
    # Without --turn, EVERY turn is examined - including a turn that staged
    # nothing because its only file was cut off mid-block.
    all_reports = {t: session.parse_report(t) for t in session.turns_with_reports()}
    sel_turns = sorted(set(turns)) if turns else sorted(all_reports)
    reports = {t: all_reports.get(t) or session.parse_report(t) for t in sel_turns}
    for t, rep in reports.items():
        if not rep:
            continue
        for p in rep.get("problems", []):
            if p.get("severity") != "error":
                continue
            k = p.get("key")
            if k and k in skip_keys:
                continue
            if k and k in chosen and int(chosen[k].get("turn", 0)) > t:
                continue
            if not k and any((r or {}).get("repairs") == t for tt, r in all_reports.items() if tt > t):
                continue
            blocking.append(f"turn {t}, reply line {p.get('line')}: {p.get('message')}")

    dump: Optional[Dict[str, str]] = None
    attach: Optional[Dict[str, List[str]]] = None
    out: List[Proposal] = []
    for k in order:
        r = chosen[k]
        art = session.read_artifact(r)
        if art is None:
            blocking.append(f"staged artifact missing for {r['path']} (turn {r.get('turn')})")
            continue
        staged = session.dir / r["staged"]
        if r.get("sha256") and staged.exists() and sha256_bytes(staged.read_bytes()) != r["sha256"]:
            if not r["staged"].endswith(".edits.json") and "kind" in r:
                info.append(f"{r['path']}: staged file was edited by hand after staging - using your edited version")
        kind = r.get("kind", "file")
        prop = Proposal(raw_path=r["path"], kind=kind, source=f"turn {r.get('turn')}",
                        base_sha=r.get("base_sha") if "base_sha" in r else None,
                        after_sha=r.get("after_sha"))
        if kind == "edit":
            prop.edits = art                       # type: ignore[assignment]
        else:
            prop.content = art                     # type: ignore[assignment]
            if dump is None:
                dump = codebase_versions(session.messages, PROJECT_ROOT)
                attach = attachment_versions(session.messages)
            bases = []
            if k in dump:
                bases.append(dump[k])
            bases += (attach or {}).get(k.rsplit("/", 1)[-1], [])
            for er in session.rows():
                ek = er.get("key") or _key_or_none(er["path"])
                if ek == k and er.get("kind", "file") == "file" and int(er.get("turn", 0)) < int(r.get("turn", 0)):
                    t = session.read_artifact(er)
                    if isinstance(t, str):
                        bases.append(t)
            prop.known_bases = bases
        if "kind" not in r:
            prop.notes.append("staged by the older kimicli (whole-file, no staging hash)")
        out.append(prop)
    return out, blocking, info


def proposals_from_text(text: str, source: str) -> Tuple[List[Proposal], List[str], ParseResult]:
    pr = parse_changes(text)
    groups, gprobs = group_blocks(pr, PROJECT_ROOT)
    gprobs += announcement_problems(pr, groups, PROJECT_ROOT)
    blocking = [f"reply line {p.line}: {p.message}" for p in pr.problems + gprobs if p.severity == "error"]
    return [_proposal_from_group(g, source, PROJECT_ROOT) for g in groups], blocking, pr


# ==========================================================================
# --apply-fixes: pass 1 decides, pass 2 executes, or nothing happens
# ==========================================================================

def options_from_args(args: argparse.Namespace) -> ApplyOptions:
    return ApplyOptions(
        allow_new_files=bool(getattr(args, "allow_new_files", False)),
        allow_new_dirs=bool(getattr(args, "allow_new_dirs", False)),
        allow_shrink=bool(getattr(args, "allow_shrink", False)),
        allow_stale=bool(getattr(args, "allow_stale", False)),
        skip_checks=bool(getattr(args, "skip_checks", False)),
    )


def _preview_path(session, source: Optional[Path]) -> Path:
    """Where this apply's diff is written.

    A session keeps its own directory, so the diff lives beside the reply it
    came from. A FILE-based apply used to write OUT_DIR/preview_apply.diff
    unconditionally, which meant the next FILE-based apply silently destroyed
    the record of the previous one. Keyed to the source file's stem instead,
    and kept next to that file when it already sits under .kimi_out.
    """
    if session is not None:
        return session.dir / "preview_apply.diff"
    if source is None:
        return OUT_DIR / "preview_apply.diff"
    name = f"preview_apply_{source.stem}.diff"
    try:
        inside = str(source.resolve().parent).startswith(str(OUT_DIR.resolve()))
    except OSError:
        inside = False
    return (source.resolve().parent if inside else OUT_DIR) / name


def run_apply(proposals: List[Proposal], args: argparse.Namespace, *,
             preview_source: Optional[Path] = None,
              blocking: Optional[List[str]] = None, session: Optional["Session"] = None,
              meta: Optional[Dict[str, Any]] = None) -> int:
    blocking = blocking or []
    if not proposals and not blocking:
        print("No '### EDIT:' or '### FILE:' blocks to apply.")
        return 1
    applier = Applier(PROJECT_ROOT, BACKUP_DIR, options_from_args(args))
    print(f"\nPASS 1 - resolving {len(proposals)} file change(s) against your tree. Nothing is written.\n")
    plans = applier.validate(proposals)
    for pl in plans:
        if pl.problems:
            mark = "FAIL"
        elif pl.action == "identical":
            mark = "same"
        else:
            mark = pl.action.upper()
        extra = ""
        if pl.proposal.kind == "edit" and pl.outcomes:
            a = sum(1 for o in pl.outcomes if o.status == "applied")
            h = sum(1 for o in pl.outcomes if o.status == "have")
            extra = f"  ({a} edit(s) apply" + (f", {h} already present" if h else "") + ")"
        elif pl.proposal.kind == "file" and pl.new_text is not None and pl.action != "identical":
            old_n = (pl.old_text or "").count("\n") + (1 if pl.old_text else 0)
            extra = f"  (whole file, {old_n} -> {pl.new_text.count(chr(10)) + 1} lines)"
        print(f"  [{mark:^6}] {pl.rel or pl.proposal.raw_path}{extra}   <- {pl.proposal.source}")
        for n in pl.notes:
            print(f"            note: {n}")
        for prob in pl.problems:
            print(f"            !! {prob}")

    bad = [p for p in plans if p.problems]
    if blocking and not getattr(args, "accept_parse_errors", False):
        print("\nThe reply itself had problems that no later turn fixed:")
        for b in blocking:
            print(f"  !! {b}")
    preview = _preview_path(session, preview_source)
    changed_lines = applier.write_preview(plans, preview)

    if bad or (blocking and not getattr(args, "accept_parse_errors", False)):
        print(f"\nVALIDATION FAILED - {len(bad)} of {len(plans)} file(s) rejected"
              + (f", {len(blocking)} reply problem(s)" if blocking else "")
              + ". NO FILES WERE MODIFIED.")
        if session is not None:
            last_turn = max((int(r.get("turn", 0)) for r in session.rows()), default=0)
            body = build_repair_prompt(bad, [ParseProblem(0, b) for b in blocking], last_turn)
            if body:
                rp = session.dir / "repair_apply.md"
                atomic_write(rp, body + f"\n[kimicli-repair-of-turn: {last_turn}]\n")
                print("\nReady-made repair prompt (cheapest while the cache is warm):")
                print(f"\n  python kimicli.py --resume {session.id} --prompt {_rel_display(rp)} --request-code")
        return 1

    todo = [p for p in plans if p.changes]
    print(f"\nPASS 1 clean: {len(plans)} file(s) OK, {len(todo)} to write, "
          f"{len(plans) - len(todo)} already identical.")
    print(f"Preview of every change ({changed_lines} lines): {_rel_display(preview)}")
    if not todo:
        print("Nothing to write - the tree already matches.")
        return 0
    if args.dry_run:
        print("\nDRY RUN - nothing was written. Re-run without --dry-run to apply.")
        return 0
    if not args.yes:
        print()
        if not confirm(f"Write {len(todo)} file(s) to {PROJECT_ROOT}? (verified backups are taken first)"):
            print("Cancelled. Nothing was modified.")
            return 1
    print("\nPASS 2 - writing (backup -> verify -> write -> verify, rollback on any failure):\n")
    try:
        manifest = applier.apply(plans, meta or {})
    except ApplyAborted as exc:
        print(f"\n!! {exc}")
        return 1
    for e in manifest["entries"]:
        print(f"  [ok  ] {e['action']:<7} {e['path']}")
    git = manifest.get("git") or {}
    print(f"\nDone. {len(manifest['entries'])} file(s) written and verified. Manifest {manifest['id']}.")
    if git.get("ref"):
        print(f"Independent git snapshot of the tree before this apply: {git['ref']} ({git['snapshot'][:10]})")
    print(f"To revert exactly:  python kimicli.py --undo {manifest['id']}")
    return 0


# ==========================================================================
# Prompt assembly
# ==========================================================================

METHOD_RULES = """\
You are a principal software engineer working on AA, a large Python codebase \
maintained by one self-taught developer. Hold to this method without being reminded:

- TRACE BEFORE WRITING. Read the live call path in the supplied codebase before \
proposing anything. Never infer a mechanism from a shape. If you read one file and \
inferred the rest, say so in that sentence.
- VERIFY OR DISCLAIM. You cannot execute anything here. Any claim you have not \
verified from the supplied text must carry the words "I have not verified this" in \
the same sentence as the claim. Do not soften this into a general disclaimer at the end.
- REUSE BEFORE CREATING. This codebase's signature defect is capability that was \
built and never connected. Assume the thing you want already exists somewhere in the \
tree; quote the grep-equivalent evidence (file and line) before concluding it does not.
- MEASUREMENT BEFORE EXPLANATION. When asked why something is slow or broken, first \
state the cheapest test that would prove you wrong.
- OWN MISTAKES PLAINLY. If a number or claim you gave earlier was wrong, lead with that.
- SAY WHAT YOU CANNOT PROMISE. End substantial answers with what the proposed change \
does not cover.

Be concrete and specific. Prefer file:line citations over description. Do not pad, do \
not restate the request, and do not produce a summary of what you are about to do."""

APPLIER_CONTRACT = """\
Your code changes are applied by a script, not a person. It is strict and all-or-nothing:

- It writes EXACTLY the paths you write. Use full repo-relative paths as they appear in the
  codebase headers (packages/auto_apply/src/...). A path that does not exist is never re-routed
  to a similarly named file, and a new file that would duplicate an existing one is refused.
- EDIT blocks: every SEARCH must match the current file text exactly once. Zero matches, or two
  or more, reject the whole batch.
- It cannot delete, rename or move files. State those as manual steps in prose (this project
  retires files with retire.py rather than deleting them).
- New files need the human's --allow-new-files; new directories need --allow-new-dirs.
- A whole-file FILE block that drops a file below 60% of its lines is rejected as truncated.
- A batch that fails to import (a name used but never imported, an import of a name another
  file no longer defines) is rejected before anything is written.
- One rejected block rejects the ENTIRE batch. Nothing is ever half-applied.
"""

CODE_CONTRACT = """\
OUTPUT CONTRACT FOR CODE (kimicli v3) - parsed by a script, so it is strict. It replaces any
earlier output-format rule in this conversation (including "complete files only"), except
where my request above names a block type for a specific file.

TWO BLOCK TYPES

1) EDIT - the default for EVERY file that already exists. Send only what changes:

### EDIT: packages/auto_apply/src/auto_apply/example.py
<<<<<<< SEARCH
    def total(self) -> int:
        return self.a + self.b
=======
    def total(self) -> int:
        \"\"\"Sum of both parts.\"\"\"
        return self.a + self.b
>>>>>>> REPLACE

2) FILE - for a NEW file, or an existing file under ~300 lines that you are rewriting almost
entirely:

### FILE: packages/auto_apply/tests/test_example.py
```python
<the complete file, first line to last>
```

EDIT RULES
- SEARCH is literal text copied character-for-character from the file as it is NOW: the
  codebase dump's version, updated by any change from this conversation the human has said
  was applied. Same indentation, same comments, same blank lines, whole lines.
- Each SEARCH must occur EXACTLY ONCE in that file. Add 2-3 unchanged neighbouring lines when
  needed to make it unique - but keep it short; never copy a whole function to change one line.
- Insert: SEARCH an adjacent existing line; REPLACE with that line plus the new lines.
  Delete: leave the REPLACE side empty.
- Several blocks for one file apply top to bottom, each to the result of the previous one.
  They must not overlap. Emit them in file order.
- Put the `### EDIT: <path>` line directly above EVERY block, even consecutive ones.
- The three markers go at column 0 on their own lines, exactly as shown. No code fence around
  an EDIT block.
- Never put "...", "# existing code", "rest unchanged" or any other placeholder in SEARCH or
  REPLACE. Both sides are literal text.

FILE RULES
- The complete file; no placeholders. Fence it with a run of backticks LONGER than any run
  inside the file (a markdown file containing ``` needs ```` or more).

BOTH
- Full repo-relative paths exactly as in the codebase headers. No absolute paths, no ../, no
  leading repo-name folder.
- Before the first block, list every file you will change, one line each:
  path - EDIT or FILE - what changes and why.
- The whole change goes in ONE reply. If you emit a file again later in this conversation,
  re-emit ALL of its blocks (or the whole FILE): the latest emission for a file replaces
  every earlier one.
- After the LAST block, write this line on its own:
### END CHANGES
  Nothing after that line is ever applied, so alternative or illustrative code (e.g. a
  BETTER IDEA section) belongs after it.
- Explanations go outside blocks. Deletions, renames and moves are manual steps in prose.
"""


def load_playbook(playbook_file: Path, tag: str) -> Optional[str]:
    """Pull one '## P<n> - title' section's quoted prompt out of the playbook."""
    if not playbook_file.exists():
        logger.warning("playbook not found: %s", playbook_file)
        return None
    text = read_text(playbook_file)
    heads = list(re.finditer(r"(?m)^##\s+(P-?\w+)\s*[-\u2014]\s*(.+)$", text))
    for i, m in enumerate(heads):
        if m.group(1).upper() == tag.upper():
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            body = text[m.end():end]
            quoted = [ln[2:] if ln.startswith("> ") else ln[1:] if ln.startswith(">") else None
                      for ln in body.splitlines()]
            lines = [ln for ln in quoted if ln is not None]
            if not lines:
                return body.strip()
            return "\n".join(lines).strip()
    return None


def list_playbook(playbook_file: Path) -> None:
    if not playbook_file.exists():
        print(f"No playbook at {playbook_file}")
        return
    text = read_text(playbook_file)
    print(f"\nPrompts in {playbook_file.name}:\n")
    for m in re.finditer(r"(?m)^##\s+(P-?\w+)\s*[-\u2014]\s*(.+)$", text):
        print(f"  {m.group(1):<5} {m.group(2).strip()}")
    print("\nUse:  python kimicli.py --playbook P3 --chat\n")


@dataclass
class Context:
    messages: List[Dict[str, Any]]
    parts: List[Tuple[str, int]]
    cache_key: str

    @property
    def total_tokens(self) -> int:
        return sum(t for _, t in self.parts)


def build_context(args: argparse.Namespace) -> Context:
    """Order matters and is the whole caching strategy:

        [0] codebase        huge, stable  -> the cached prefix
        [1] method rules    stable
        [2] master TODO     semi-stable
        [3] memory          volatile
        [4] attachments + prompt (user)   volatile

    Anything that changes must sit as late as possible: a cache hit covers the
    identical leading tokens only, so one edited byte near the front costs you
    the whole prefix.
    """
    parts: List[Tuple[str, int]] = []
    messages: List[Dict[str, Any]] = []
    cache_seed = "no-codebase"

    if not args.no_codebase:
        cb = Path(args.codebase).expanduser()
        if cb.exists():
            dump = read_text(cb)
            if args.exclude:
                dump, report = filter_dump(dump, args.exclude)
                if report:
                    print(report)
            messages.append({"role": "system", "content":
                             f"<codebase name=\"{cb.name}\">\n{dump}\n</codebase>"})
            parts.append((f"codebase ({cb.name})", est_tokens(dump)))
            cache_seed = sha256(dump)[:32]
        else:
            logger.warning("codebase not found at %s - continuing without it", cb)

    messages.append({"role": "system", "content": METHOD_RULES})
    parts.append(("method rules", est_tokens(METHOD_RULES)))

    messages.append({"role": "system", "content": APPLIER_CONTRACT})
    parts.append(("applier contract", est_tokens(APPLIER_CONTRACT)))

    todo = Path(args.todo) if args.todo else (PROJECT_ROOT / "AA_MASTER_TODO.md")
    if not args.no_todo and todo.exists():
        body = read_text(todo)
        messages.append({"role": "system", "content":
                         f"<authoritative_todo file=\"{todo.name}\">\n{body}\n</authoritative_todo>\n"
                         f"This file supersedes docs/adr/* and every docstring in the codebase, "
                         f"which are known to be stale."})
        parts.append((f"todo ({todo.name})", est_tokens(body)))

    mem = OUT_DIR / "memory.md"
    if args.memory and mem.exists() and mem.stat().st_size > 0:
        body = read_text(mem)
        messages.append({"role": "system", "content": f"<notes_from_earlier_sessions>\n{body}\n</notes_from_earlier_sessions>"})
        parts.append(("memory", est_tokens(body)))

    user_chunks: List[str] = []
    seen_attach: set = set()
    for spec in (args.attach or []):
        p = Path(spec).expanduser()
        if not p.exists():
            logger.warning("attachment not found: %s", spec)
            continue
        body = read_text(p)
        digest = sha256(body)
        if digest in seen_attach:
            logger.warning("skipping duplicate attachment: %s", p.name)
            continue
        seen_attach.add(digest)
        user_chunks.append(
            f"<attachment name=\"{_attach_label(p)}\">\n{body}\n</attachment>"
        )
        parts.append((f"attach {p.name}", est_tokens(body)))

    prompt_text = ""
    if args.playbook:
        pb = load_playbook(Path(args.playbook_file), args.playbook)
        if pb:
            prompt_text = pb
            unfilled = re.findall(r"<[a-z][^>]{2,40}>", pb)
            if unfilled:
                logger.warning("playbook %s still has placeholders: %s",
                               args.playbook, ", ".join(sorted(set(unfilled))[:5]))
        else:
            logger.warning("playbook section %s not found", args.playbook)

    if args.prompt:
        p = Path(args.prompt)
        extra = read_text(p) if (p.exists() and p.is_file()) else args.prompt
        if p.exists() and p.is_file():
            logger.info("prompt loaded from %s", p.name)
        prompt_text = (prompt_text + "\n\n" + extra).strip() if prompt_text else extra

    if args.request_code:
        prompt_text = (prompt_text + "\n\n" + CODE_CONTRACT).strip()

    if prompt_text:
        user_chunks.append(prompt_text)
        parts.append(("prompt", est_tokens(prompt_text)))

    if user_chunks:
        messages.append({"role": "user", "content": "\n\n".join(user_chunks)})

    return Context(messages=messages, parts=parts, cache_key=args.cache_key or f"aa-{cache_seed}")


# ==========================================================================
# Kimi client
# ==========================================================================

class Kimi:
    def __init__(self, api_key: str, base_url: str, timeout: float = REQUEST_TIMEOUT_S):
        try:
            from openai import OpenAI
        except ImportError:
            print("The 'openai' package is required:  python -m pip install --upgrade 'openai>=1.0'")
            raise SystemExit(2)
        # max_retries=0 is deliberate. The SDK's default is to retry silently,
        # and a retried 600k-token prompt is a second 600k-token bill.
        self.client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout, max_retries=0)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    # -- account ------------------------------------------------------
    def balance(self) -> Optional[Dict[str, Any]]:
        try:
            import httpx
            r = httpx.get(f"{self.base_url}/users/me/balance",
                          headers={"Authorization": f"Bearer {self.api_key}"}, timeout=30)
            r.raise_for_status()
            return r.json().get("data")
        except Exception as exc:
            logger.warning("balance check failed: %s", exc)
            return None

    def count_tokens(self, messages: List[Dict[str, Any]], model: str) -> Optional[int]:
        """Exact prompt size from Moonshot's tokenizer, cached by content hash
        so a 3 MB dump is only ever uploaded once per version."""
        key = sha256(model + "|" + "".join(str(m.get("content", "")) for m in messages))
        cache_file = OUT_DIR / "token_cache.json"
        cache = {}
        if cache_file.exists():
            try:
                cache = json.loads(read_text(cache_file))
            except Exception:
                cache = {}
        if key in cache:
            return int(cache[key])
        try:
            import httpx
            r = httpx.post(f"{self.base_url}/tokenizers/estimate-token-count",
                           headers={"Authorization": f"Bearer {self.api_key}"},
                           json={"model": model, "messages": messages}, timeout=180)
            r.raise_for_status()
            total = int(r.json()["data"]["total_tokens"])
        except Exception as exc:
            logger.debug("token count endpoint unavailable: %s", exc)
            return None
        cache[key] = total
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write(cache_file, json.dumps(cache)[:2_000_000])
        return total

    # -- the call -----------------------------------------------------
    def stream(self, messages: List[Dict[str, Any]], session: Session, *,
               model: str, effort: str, max_completion: int, cache_key: str,
               show_thinking: bool, prediction: Optional[str] = None) -> Dict[str, Any]:
        """Stream a completion. Every token is written to disk as it arrives."""
        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_completion_tokens": max_completion,
            "reasoning_effort": effort,
            "prompt_cache_key": cache_key,
        }
        if prediction:
            kwargs["prediction"] = {"type": "content", "content": prediction}
        # temperature / top_p / n / penalties are fixed on K3 - never send them.

        content: List[str] = []
        reasoning: List[str] = []
        usage: Dict[str, Any] = {}
        finish = None
        started = time.time()
        first_token_at: Optional[float] = None
        printed_thinking_header = False

        try:
            stream = self.client.chat.completions.create(**kwargs)
        except Exception as exc:
            explain_api_error(exc)
            raise

        try:
            for chunk in stream:
                if getattr(chunk, "usage", None):
                    try:
                        usage = chunk.usage.model_dump()
                    except Exception:
                        usage = dict(chunk.usage or {})
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if getattr(choice, "finish_reason", None):
                    finish = choice.finish_reason

                think = getattr(delta, "reasoning_content", None)
                if think:
                    if first_token_at is None:
                        first_token_at = time.time()
                    reasoning.append(think)
                    session.write(think, to_thinking=True)
                    if show_thinking:
                        if not printed_thinking_header:
                            print("\n--- thinking ---")
                            printed_thinking_header = True
                        sys.stdout.write(think)
                        sys.stdout.flush()

                text = getattr(delta, "content", None)
                if text:
                    if first_token_at is None:
                        first_token_at = time.time()
                    if printed_thinking_header:
                        print("\n--- answer ---")
                        printed_thinking_header = False
                    content.append(text)
                    session.write(text)
                    sys.stdout.write(text)
                    sys.stdout.flush()
        except KeyboardInterrupt:
            print("\n\n[interrupted - the partial answer is already saved to transcript.md]")
            try:
                stream.close()
            except Exception:
                pass
            finish = "interrupted"
        except Exception as exc:
            print()
            explain_api_error(exc)
            finish = "error"

        elapsed = time.time() - started
        body = "".join(content)
        return {
            "content": body,
            "reasoning": "".join(reasoning),
            "usage": usage,
            "finish_reason": finish,
            "elapsed": elapsed,
            "ttft": (first_token_at - started) if first_token_at else None,
        }


# ==========================================================================
# Error explanation (mapped from docs/api/errors)
# ==========================================================================

ERROR_HELP = {
    "content_filter": "Content safety review rejected the request. Rephrase and resend.",
    "invalid_request_error": "Bad request. If the message mentions token length, the prompt is "
                             "over the 1M context window - drop the codebase (--no-codebase), "
                             "filter it (--exclude docs), or send fewer attachments.",
    "invalid_authentication_error": "The key is malformed. Keys from platform.kimi.ai and "
                                    "platform.kimi.com are NOT interchangeable - the key must "
                                    "match the base URL.",
    "incorrect_api_key_error": "Key missing or wrong. Check MOONSHOT_API_KEY in your .env.",
    "permission_denied_error": "Not permitted. Often an IP allowlist on the organisation.",
    "resource_not_found_error": "Model name wrong, or your account cannot access it. K3 unlocks "
                                "after a top-up of at least $1.",
    "engine_overloaded_error": "Moonshot's side is saturated - this is the 'too many users' one. "
                               "Wait and retry; topping up does not help.",
    "exceeded_current_quota_error": "Balance is empty or the account is disabled. "
                                    "Run: python kimicli.py --balance",
    "rate_limit_reached_error": "You hit an org limit (concurrency / RPM / TPM / TPD). A request "
                                "needs its whole token count as TPM headroom in one minute. Check "
                                "platform.kimi.ai/console/limits and set KIMI_TPM in .env to match; "
                                f"this run assumed {ACCOUNT_TPM:,} TPM.",
    "client_closed_request": "The connection dropped before the answer finished.",
    "server_error": "Moonshot internal error. Retry; quote the request id if it persists.",
    "server_unavailable": "Service temporarily unavailable (node scaling/maintenance).",
}


def explain_api_error(exc: Exception) -> None:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    etype = emsg = None
    if isinstance(body, dict):
        err = body.get("error") or body
        etype, emsg = err.get("type"), err.get("message")
    if not emsg:
        emsg = str(exc)
    rid = getattr(exc, "request_id", None)

    print("\n" + "!" * 70)
    print(f"API CALL FAILED{f'  (HTTP {status})' if status else ''}")
    if etype:
        print(f"  type    : {etype}")
    print(f"  message : {str(emsg)[:400]}")
    if rid:
        print(f"  request : {rid}   <- quote this to api-service@moonshot.ai")
    help_text = ERROR_HELP.get(etype or "")
    if not help_text:
        low = str(emsg).lower()
        if "timeout" in low or "timed out" in low:
            help_text = ("Timed out client-side. This script streams, so a timeout here usually "
                         "means the connection stalled rather than the model being slow. Nothing "
                         "was lost: check transcript.md for whatever arrived.")
        elif "504" in low:
            help_text = "Gateway timeout at 900s - only happens on non-streaming calls."
    if help_text:
        print(f"\n  {help_text}")
    print("!" * 70 + "\n")


# ==========================================================================
# Preflight
# ==========================================================================

def preflight(ctx: Context, kimi: Kimi, args: argparse.Namespace) -> bool:
    print("\n" + "-" * 70)
    print("PREFLIGHT")
    print("-" * 70)
    width = max((len(n) for n, _ in ctx.parts), default=10)
    for name, tok in ctx.parts:
        print(f"  {name:<{width}}  {tok:>10,} tok")
    est = ctx.total_tokens
    print(f"  {'':<{width}}  {'-' * 10}")
    print(f"  {'input (est)':<{width}}  {est:>10,} tok")

    exact = None
    if not args.no_count:
        exact = kimi.count_tokens(ctx.messages, args.model)
        if exact:
            print(f"  {'input (exact)':<{width}}  {exact:>10,} tok"
                  f"   [tokenizer; local estimate was off by {abs(exact - est) / max(exact, 1):.0%}]")
    # An exact count is authoritative. Without one, guard the window on a
    # pessimistic reading: est_tokens is calibrated, not conservative.
    n_in = exact if exact else int(est * EST_WINDOW_SAFETY)
    if not exact:
        print(f"  {'window guard uses':<{width}}  {n_in:>10,} tok"
              f"   [estimate x{EST_WINDOW_SAFETY}; no tokenizer count this call]")

    if n_in > CONTEXT_WINDOW:
        print(f"\n  STOP: {n_in:,} tokens exceeds the {CONTEXT_WINDOW:,} context window.")
        print("  Use --exclude docs --exclude tests, or --no-codebase.")
        return False
    if n_in + args.max_completion > CONTEXT_WINDOW:
        room = CONTEXT_WINDOW - n_in
        print(f"\n  NOTE: input + max_completion_tokens exceeds the window; "
              f"capping output at {room:,}.")
        args.max_completion = max(room - 1024, 4096)

    miss = cost_of(n_in, 0, 0)
    hit = cost_of(n_in, n_in, 0)
    out_max = args.max_completion * PRICE_OUT / 1e6
    print(f"\n  input if cache MISSES : {money(miss)}")
    print(f"  input if cache HITS   : {money(hit)}   (10x cheaper - identical prefix required)")
    print(f"  output, worst case    : {money(out_max)}  ({args.max_completion:,} tok @ ${PRICE_OUT}/M)")
    print(f"  reasoning effort      : {args.effort}   (reasoning bills as output)")

    if n_in > ACCOUNT_TPM:
        print(f"\n  ! {n_in:,} tokens in one request exceeds this account's "
              f"{ACCOUNT_TPM:,} TPM ceiling. If you see"
              f"\n    rate_limit_reached_error, that is the reason, not server load."
              f"\n    (Set KIMI_TPM in .env if your tier has changed.)")

    bal = kimi.balance()
    if bal:
        print(f"\n  balance available     : ${bal.get('available_balance', 0):,.2f}"
              f"  (voucher ${bal.get('voucher_balance', 0):,.2f} / "
              f"cash ${bal.get('cash_balance', 0):,.2f})")
        if bal.get("available_balance", 0) <= 0:
            print("  STOP: balance is zero - the API will refuse this call.")
            return False

    worst = miss + out_max
    if worst > args.max_spend:
        print(f"\n  STOP: worst case {money(worst)} exceeds --max-spend {money(args.max_spend)}.")
        print("  Raise the cap deliberately if you mean it.")
        return False
    print("-" * 70)

    if args.yes:
        return True
    return confirm("Send this request?", default_no=False)


# ==========================================================================
# Turn execution
# ==========================================================================

def do_turn(kimi: Kimi, session: Session, args: argparse.Namespace, label: str = "") -> Dict[str, Any]:
    session.turn += 1
    session.banner("YOU", label)
    last_user = next((m for m in reversed(session.messages) if m["role"] == "user"), None)
    if last_user:
        text = last_user["content"]
        session.write(text if len(text) < 8000 else text[:8000] + "\n[... prompt truncated in transcript ...]\n")
    session.banner("KIMI", f"effort={args.effort}")

    print()
    result = kimi.stream(
        session.messages, session,
        model=args.model, effort=args.effort, max_completion=args.max_completion,
        cache_key=args.cache_key_resolved, show_thinking=args.show_thinking,
        prediction=args.prediction_text,
    )

    assistant: Dict[str, Any] = {"role": "assistant", "content": result["content"] or ""}
    # K3 uses Preserved Thinking: keep reasoning_content in history or the model
    # loses its own chain across turns.
    if result["reasoning"]:
        assistant["reasoning_content"] = result["reasoning"]
    session.messages.append(assistant)

    usage = result["usage"] or {}
    if usage:
        session.usage.add(usage)
        session.ledger_entry(usage, args.effort, note=label)
    session.save()

    summary: Optional[StageSummary] = None
    try:
        summary = stage_turn(session, session.turn, result["content"] or "", result["finish_reason"])
    except Exception as exc:                       # the reply is already saved; never lose it
        logger.exception("staging failed")
        print(f"\n!! kimicli could not stage this reply's changes: {exc}\n"
              f"   The reply is saved: {session.dir / f'reply_turn{session.turn}.md'}\n"
              f"   Try:  python kimicli.py --apply-fixes {session.dir / f'reply_turn{session.turn}.md'} --dry-run")

    print_turn_summary(result, session)
    if summary is not None:
        print_stage_summary(summary, session)
        if getattr(args, "request_code", False) and not summary.parse.blocks:
            print("\n  ! Code was requested, but the reply contains no '### EDIT:' / '### FILE:' "
                  "blocks. Nothing was staged.")
    return result


def print_turn_summary(result: Dict[str, Any], session: Session) -> None:
    u = result["usage"] or {}
    p = int(u.get("prompt_tokens") or 0)
    c = int(u.get("cached_tokens") or (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    o = int(u.get("completion_tokens") or 0)
    print("\n" + "-" * 70)
    if result["finish_reason"] == "length":
        print("  ! finish_reason=length - the answer hit max_completion_tokens and is CUT OFF.")
        print("    Raise --max-completion, or ask for fewer files per turn.")
    if p:
        pct = (c / p * 100) if p else 0
        print(f"  input {p:,} tok ({c:,} cached = {pct:.0f}%)   output {o:,} tok"
              f"   this turn {money(cost_of(p, c, o))}")
        print(f"  session total {money(session.usage.cost)} over {session.usage.calls} call(s)")
    else:
        print("  usage not reported (stream ended early) - see the ledger for prior calls")
    if result["ttft"]:
        print(f"  {result['ttft']:.0f}s to first token, {result['elapsed']:.0f}s total")
    print(f"  transcript: {session.transcript}")
    print("-" * 70)


# ==========================================================================
# Chat loop
# ==========================================================================

CHAT_HELP = """
  /exit            end the session (everything is already saved)
  /cost            spend for this session and lifetime
  /effort low|high|max     change reasoning effort for the next turn
  /files           list the change blocks staged this session
  /apply           dry-run the applier on this session (writes nothing)
  /remember <text> append a line to .kimi_out/memory.md for future sessions
  /attach <path>   add a file to the next message
  /paste           multi-line input; finish with a single '.' on its own line
  /help            this list
"""


def chat_loop(kimi: Kimi, session: Session, args: argparse.Namespace) -> None:
    print("\n" + "=" * 70)
    print(f"KIMI K3 - session {session.id}")
    print(f"Everything is written to {session.dir}")
    print("Type /help for commands.")
    print("=" * 70)

    pending_attachments: List[str] = []
    while True:
        try:
            line = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not line:
            continue

        if line.startswith("/"):
            cmd, _, rest = line.partition(" ")
            cmd = cmd.lower()
            if cmd in ("/exit", "/quit"):
                break
            if cmd == "/help":
                print(CHAT_HELP)
                continue
            if cmd == "/cost":
                print(f"\n  session {session.id}: {money(session.usage.cost)} "
                      f"over {session.usage.calls} call(s)")
                print(f"  lifetime: {money(lifetime_spend())}")
                continue
            if cmd == "/effort":
                if rest.strip() in ("low", "high", "max"):
                    args.effort = rest.strip()
                    print(f"  reasoning effort -> {args.effort}")
                else:
                    print("  usage: /effort low|high|max")
                continue
            if cmd == "/files":
                rows = session.rows()
                if rows:
                    for row in rows:
                        print(f"  turn {row.get('turn')}: {str(row.get('kind', 'file')).upper():<4} "
                              f"{row['path']}  ({row.get('blocks', 1)} block(s), "
                              f"trial {row.get('trial', '?')})")
                else:
                    print("  no change blocks staged yet")
                continue
            if cmd == "/apply":
                props, blocking, _info = load_session_proposals(session)
                ns = argparse.Namespace(
                    dry_run=True, yes=False,
                    allow_new_files=getattr(args, "allow_new_files", False),
                    allow_new_dirs=getattr(args, "allow_new_dirs", False),
                    allow_shrink=getattr(args, "allow_shrink", False),
                    allow_stale=getattr(args, "allow_stale", False),
                    skip_checks=getattr(args, "skip_checks", False),
                    accept_parse_errors=False)
                run_apply(props, ns, blocking=blocking, session=session)
                continue
            if cmd == "/remember":
                if rest.strip():
                    OUT_DIR.mkdir(parents=True, exist_ok=True)
                    with open(OUT_DIR / "memory.md", "a", encoding="utf-8") as fh:
                        fh.write(f"- {rest.strip()}\n")
                    print("  noted for future sessions (takes effect next run with --memory)")
                continue
            if cmd == "/attach":
                p = Path(rest.strip().strip('"'))
                if p.exists():
                    pending_attachments.append(str(p))
                    print(f"  will attach {p.name} ({est_tokens(read_text(p)):,} tok) to the next message")
                else:
                    print(f"  not found: {p}")
                continue
            if cmd == "/paste":
                buf: List[str] = []
                print("  (multi-line; end with a single '.' on its own line)")
                while True:
                    try:
                        ln = input()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if ln.strip() == ".":
                        break
                    buf.append(ln)
                line = "\n".join(buf)
                if not line.strip():
                    continue
            else:
                print(f"  unknown command {cmd}; /help for the list")
                continue

        chunks: List[str] = []
        for spec in pending_attachments:
            p = Path(spec)
            chunks.append(
                f"<attachment name=\"{_attach_label(p)}\">\n{read_text(p)}\n</attachment>"
            )
        pending_attachments.clear()
        chunks.append(line)
        session.messages.append({"role": "user", "content": "\n\n".join(chunks)})

        try:
            do_turn(kimi, session, args)
        except Exception:
            session.messages.pop()  # keep history clean so the next turn still caches
            continue

    print(f"\nSession {session.id} saved.  {money(session.usage.cost)} this session.")
    print(f"Resume it any time with:  python kimicli.py --resume {session.id}")


def lifetime_spend() -> float:
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for ln in read_text(LEDGER).splitlines():
        try:
            total += float(json.loads(ln).get("cost_usd", 0))
        except Exception:
            continue
    return total


def print_stats() -> None:
    if not LEDGER.exists():
        print("No calls recorded yet.")
        return
    rows = []
    for ln in read_text(LEDGER).splitlines():
        try:
            rows.append(json.loads(ln))
        except Exception:
            pass
    total = sum(r.get("cost_usd", 0) for r in rows)
    cached = sum(r.get("cached", 0) for r in rows)
    prompt = sum(r.get("prompt", 0) for r in rows)
    out = sum(r.get("completion", 0) for r in rows)
    print(f"\n  calls          : {len(rows)}")
    print(f"  input tokens   : {prompt:,}  ({cached:,} cached = {cached / max(prompt, 1) * 100:.0f}%)")
    print(f"  output tokens  : {out:,}")
    print(f"  total spend    : {money(total)}")
    if prompt:
        saved = (cached * (PRICE_IN_FRESH - PRICE_IN_CACHED)) / 1e6
        print(f"  saved by cache : {money(saved)}")
    print("\n  last 5 calls:")
    for r in rows[-5:]:
        print(f"    {r['ts']}  {r.get('effort', '?'):<4} "
              f"in {r.get('prompt', 0):>9,} ({r.get('cached', 0):>9,} cached) "
              f"out {r.get('completion', 0):>7,}  {money(r.get('cost_usd', 0))}")
    print()


# ==========================================================================
# Self-test: proves the parser, applier, rollback and undo on THIS machine
# (Windows file locking, OneDrive, CRLF) in a throwaway folder. Never touches
# your repo. Run it after installing a new kimicli.py.
# ==========================================================================

def run_selftest() -> int:
    results: List[Tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, bool(ok), detail))

    tmp = Path(tempfile.mkdtemp(prefix="kimicli_selftest_"))
    root = tmp / "AA"
    root.mkdir()
    bdir = root / ".kimi_backups"
    quiet = io.StringIO()
    try:
        # ---- fixtures -----------------------------------------------------
        (root / "pkg").mkdir()
        (root / "pkg" / "__init__.py").write_bytes(b"")
        (root / "pkg" / "crlf.py").write_bytes(
            b"\xef\xbb\xbfimport os\r\n\r\ndef a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2")
        (root / "pkg" / "mixed.py").write_bytes(b"x = 1\r\ny = 2\nz = 3\r\n")
        (root / "pkg" / "lib.py").write_bytes(b"def helper():\n    return 42\n")
        (root / "pkg" / "other").mkdir()
        (root / "pkg" / "other" / "utils.py").write_bytes(b"# unrelated module\n" * 50)
        (root / "notes.md").write_bytes(b"# Notes\n\nOld line\n")
        originals = {p.relative_to(root).as_posix(): p.read_bytes()
                     for p in root.rglob("*") if p.is_file()}

        def fresh_applier(**kw: Any) -> Applier:
            return Applier(root, bdir, ApplyOptions(**kw))

        def props_from(reply: str) -> Tuple[List[Proposal], ParseResult, List[ParseProblem]]:
            pr = parse_changes(reply)
            groups, gp = group_blocks(pr, root)
            return [_proposal_from_group(g, "selftest", root) for g in groups], pr, gp

        # ---- 1. parser -----------------------------------------------------
        reply = (
            "Plan: two edits, one new file.\n\n"
            "### EDIT: AA/pkg/crlf.py\n<<<<<<< SEARCH\ndef a():\n    return 1\n=======\n"
            "def a():\n    return 10\n>>>>>>> REPLACE\n\n"
            "### EDIT: pkg/crlf.py\n<<<<<<< SEARCH\ndef b():\n    return 2\n=======\n"
            "def b():\n    return 20\n>>>>>>> REPLACE\n\n"
            "### EDIT: pkg/mixed.py\n<<<<<<< SEARCH\ny = 2\n=======\ny = 22\nw = 4\n>>>>>>> REPLACE\n\n"
            "### FILE: pkg/newdir/guide.md\n````markdown\n# Guide\n\n```python\nprint(1)\n```\n\nEnd\n````\n\n"
            "### END CHANGES\n\nBETTER IDEA? Maybe:\n\n"
            "### EDIT: pkg/lib.py\n<<<<<<< SEARCH\n    return 42\n=======\n    return 0\n>>>>>>> REPLACE\n"
        )
        props, pr, gp = props_from(reply)
        check("parser: 4 blocks in 3 files, END seen, the after-END block NOT staged",
              len(pr.blocks) == 4 and len(props) == 3 and pr.end_marker and pr.blocks_after_end == 1
              and not pr.errors and not gp)
        md = [p for p in props if p.raw_path.endswith("guide.md")]
        check("parser: a markdown FILE containing ``` survives whole (```` fence)",
              bool(md) and md[0].content is not None and md[0].content.endswith("End\n")
              and "```python" in (md[0].content or ""))
        cut = parse_changes("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\n    return 42\n=======\n    return")
        check("parser: a reply cut off mid-block is an ERROR, not a silent drop",
              len(cut.errors) == 1 and not cut.blocks)
        stray = parse_changes("### PATCH: pkg/lib.py\n```python\n<<<<\n    return 42\n====\n    return 1\n>>>>\n```\n"
                              "### DELETE: pkg/lib.py\n```\nx\n```\n")
        check("parser: legacy PATCH markers accepted; a DELETE block is refused loudly",
              len(stray.blocks) == 1 and len(stray.errors) == 1)

        # ---- 2. apply: bytes-exact edits, CRLF + BOM + no final newline + mixed endings
        ap = fresh_applier(allow_new_files=True, allow_new_dirs=True)
        plans = ap.validate(props)
        check("pass 1 clean", all(not p.problems for p in plans),
              "; ".join(f"{p.rel}: {p.problems}" for p in plans if p.problems))
        with contextlib.redirect_stdout(quiet):
            man = ap.apply(plans, {"source": "selftest"})
        crlf = (root / "pkg" / "crlf.py").read_bytes()
        check("edits keep BOM, CRLF and the missing final newline byte-exact",
              crlf == b"\xef\xbb\xbfimport os\r\n\r\ndef a():\r\n    return 10\r\n\r\ndef b():\r\n    return 20",
              repr(crlf))
        check("mixed-ending file: untouched lines byte-identical, new lines use its dominant ending",
              (root / "pkg" / "mixed.py").read_bytes() == b"x = 1\r\ny = 22\r\nw = 4\r\nz = 3\r\n",
              repr((root / "pkg" / "mixed.py").read_bytes()))
        check("new file created in a new directory; manifest complete",
              (root / "pkg" / "newdir" / "guide.md").exists() and man["status"] == "complete")

        # ---- 3. idempotent: the same batch again writes nothing
        plans2 = fresh_applier(allow_new_files=True, allow_new_dirs=True).validate(props)
        check("re-applying an applied batch: every file 'identical', nothing to write",
              all(p.action == "identical" and not p.problems for p in plans2),
              "; ".join(f"{p.rel}:{p.action}:{p.problems}" for p in plans2))

        # ---- 4. undo: exact bytes, created file and directory removed, second undo is a no-op
        with contextlib.redirect_stdout(quiet):
            rc = undo(root, bdir, "last", assume_yes=True)
        now = {p.relative_to(root).as_posix(): p.read_bytes()
               for p in root.rglob("*") if p.is_file() and ".kimi_backups" not in p.parts}
        check("undo restores every original byte-for-byte (CRLF included)",
              rc == 0 and now == originals,
              f"rc={rc} diff={sorted(set(now) ^ set(originals))}")
        check("undo removed the directory it had created", not (root / "pkg" / "newdir").exists())
        with contextlib.redirect_stdout(quiet):
            rc2 = undo(root, bdir, "last", assume_yes=True)
        check("undo 'last' after undoing is a safe no-op", rc2 == 1 and now == {
            p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob("*") if p.is_file() and ".kimi_backups" not in p.parts})

        # ---- 5. failure on the 3rd write -> automatic, verified rollback
        calls = {"n": 0}

        def flaky(path: Path, data: bytes, keep: Optional[Path] = None) -> None:
            calls["n"] += 1
            if calls["n"] == 3:
                raise PermissionError("simulated OneDrive lock")
            write_bytes_atomic(path, data, keep)

        ap = fresh_applier(allow_new_files=True, allow_new_dirs=True)
        plans = ap.validate(props)
        err = ""
        try:
            with contextlib.redirect_stdout(quiet):
                ap.apply(plans, {"source": "selftest"}, _write=flaky)
        except ApplyAborted as exc:
            err = str(exc)
        now = {p.relative_to(root).as_posix(): p.read_bytes()
               for p in root.rglob("*") if p.is_file() and ".kimi_backups" not in p.parts}
        mans = list_manifests(bdir)
        check("a failed write rolls EVERY file back to its original bytes",
              "restored" in err and now == originals and bool(mans) and mans[-1]["status"] == "rolled_back",
              err[:120])

        # ---- 6. a SEARCH that does not match, or matches twice, writes nothing
        (root / "pkg" / "dup.py").write_bytes(b"x = 1\nx = 1\n")
        bad, _, _ = props_from("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\n    return 41\n=======\n    return 0\n>>>>>>> REPLACE\n"
                               "### EDIT: pkg/dup.py\n<<<<<<< SEARCH\nx = 1\n=======\nx = 2\n>>>>>>> REPLACE\n")
        plans = fresh_applier().validate(bad)
        check("not-found and ambiguous SEARCH both rejected",
              all(p.problems for p in plans) and "not found" in plans[0].problems[0]
              and "2 places" in plans[1].problems[0])
        (root / "pkg" / "dup.py").unlink()

        # ---- 7. additive edit already present -> 'have', never a duplicate
        add, _, _ = props_from("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\ndef helper():\n=======\n"
                               "import math\n\n\ndef helper():\n>>>>>>> REPLACE\n")
        a1 = fresh_applier().validate(add)
        with contextlib.redirect_stdout(quiet):
            fresh_applier().apply(a1, {"source": "selftest"})
        a2 = fresh_applier().validate(add)
        lib = (root / "pkg" / "lib.py").read_text(encoding="utf-8")
        check("an insertion that is already there is recognised, not inserted twice",
              lib.count("import math") == 1 and a2[0].action == "identical", a2[0].action)
        with contextlib.redirect_stdout(quiet):
            undo(root, bdir, "last", assume_yes=True)

        # ---- 8. paths
        refused = ["../x.py", "C:/Windows/x.py", "//srv/share/x.py", "pkg/a.py:hidden", "pkg/CON.py",
                   "pkg/x.py.", "kimicli.py", ".git/config", "pkg/KIMICL~1.PY", ".env"]
        pl = fresh_applier(allow_new_files=True).validate(
            [Proposal(raw_path=r, kind="file", content="x = 1\n") for r in refused])
        leaks = [r for r, p in zip(refused, pl) if not p.problems]
        check("dangerous / protected paths all refused", not leaks, f"accepted: {leaks}")
        cap = fresh_applier(allow_new_files=True, allow_new_dirs=True).validate(
            [Proposal(raw_path="pkg/newmod/utils.py", kind="file", content="# brand new\n" * 50)])
        check("a new pkg/newmod/utils.py is a CREATE - it can never overwrite pkg/other/utils.py",
              cap[0].action == "create" and cap[0].rel == "pkg/newmod/utils.py")
        mis = fresh_applier(allow_new_files=True, allow_new_dirs=True).validate(
            [Proposal(raw_path="other/utils.py", kind="file", content="# dup\n")])
        check("a mis-pathed new file that duplicates an existing one is refused",
              any("mis-pathed" in x for x in mis[0].problems))

        # ---- 8b. an EDIT naming a wrong MIDDLE directory: recovered by
        # basename, but ONLY because its anchors still match there. This is
        # the failure that threw away a 23-block batch before the fallback
        # existed: tests/pins/x.py for a file in tests/architecture/ matches
        # no path suffix, so the suffix rule alone never fired.
        WRONGDIR_REPLY = '''### EDIT: pkg/WRONG/lib.py
<<<<<<< SEARCH
def helper():
    return 42
=======
def helper():
    return 43
>>>>>>> REPLACE
'''
        NOANCHOR_REPLY = '''### EDIT: pkg/WRONG/lib.py
<<<<<<< SEARCH
def absent_function():
    pass
=======
def absent_function():
    return None
>>>>>>> REPLACE
'''
        wrongdir, _, _ = props_from(WRONGDIR_REPLY)
        wd = fresh_applier().validate(wrongdir)
        check("an EDIT naming a wrong directory is re-pointed by unique basename",
              not wd[0].problems and wd[0].rel == "pkg/lib.py"
              and any("unique basename match" in n for n in wd[0].notes),
              f"{wd[0].rel} problems={wd[0].problems}")

        noanchor, _, _ = props_from(NOANCHOR_REPLY)
        na = fresh_applier().validate(noanchor)
        check("a re-pointed file is proved by its anchors, never by its name",
              bool(na[0].problems), f"accepted, problems={na[0].problems}")

        (root / "pkg" / "other" / "lib.py").write_bytes(b"def helper():\n    return 99\n")
        amb = fresh_applier().validate(wrongdir)
        check("two files sharing the basename -> refused, candidates named",
              bool(amb[0].problems) and "does not exist" in amb[0].problems[0],
              f"problems={amb[0].problems}")
        (root / "pkg" / "other" / "lib.py").unlink()

        # ---- 9. checks that catch a change that parses but cannot run
        br, _, _ = props_from("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\n    return 42\n=======\n"
                              "    return compute_answer()\n>>>>>>> REPLACE\n")
        pl = fresh_applier().validate(br)
        check("a name used but never defined/imported is caught",
              any("compute_answer" in x for x in pl[0].problems))
        (root / "pkg" / "user.py").write_bytes(b"from pkg.lib import helper\n\nprint(helper())\n")
        rn, _, _ = props_from("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\ndef helper():\n=======\n"
                              "def helper_v2():\n>>>>>>> REPLACE\n")
        pl = fresh_applier().validate(rn)
        check("renaming a function another file imports is caught",
              any("pkg/user.py" in x for x in pl[0].problems))
        (root / "pkg" / "user.py").unlink()

        # ---- 10. Windows: a transiently locked file is retried, not failed
        real = os.replace
        state = {"n": 0}

        def locked_twice(a: str, b: str) -> None:
            state["n"] += 1
            if state["n"] <= 2:
                raise PermissionError("locked")
            real(a, b)

        os.replace = locked_twice  # type: ignore[assignment]
        try:
            write_bytes_atomic(root / "notes.md", b"# Notes\n\nNew line\n")
        finally:
            os.replace = real      # type: ignore[assignment]
        check("a file locked for a moment (OneDrive/antivirus) is written after a retry",
              (root / "notes.md").read_bytes() == b"# Notes\n\nNew line\n" and state["n"] == 3)
        (root / "notes.md").write_bytes(originals["notes.md"])

        # ---- 11. undo refuses to clobber your later edits; --force keeps them safe
        e1, _, _ = props_from("### EDIT: pkg/lib.py\n<<<<<<< SEARCH\n    return 42\n=======\n"
                              "    return 43\n>>>>>>> REPLACE\n")
        with contextlib.redirect_stdout(quiet):
            fresh_applier().apply(fresh_applier().validate(e1), {"source": "selftest"})
        (root / "pkg" / "lib.py").write_bytes(b"def helper():\n    return 99  # my own edit\n")
        with contextlib.redirect_stdout(quiet):
            rc = undo(root, bdir, "last", assume_yes=True)
        refused_ok = rc == 1 and b"my own edit" in (root / "pkg" / "lib.py").read_bytes()
        with contextlib.redirect_stdout(quiet):
            rcf = undo(root, bdir, "last", force=True, assume_yes=True)
        saved = list((bdir).rglob("undo_*/pkg/lib.py"))
        check("undo refuses when you edited the file since; --force saves your edit first",
              refused_ok and rcf == 0 and (root / "pkg" / "lib.py").read_bytes() == originals["pkg/lib.py"]
              and any(b"my own edit" in x.read_bytes() for x in saved))

        # ---- 12. case-insensitive filesystems (Windows): a wrong-case path
        # edits the real file and never renames it
        (root / "pkg" / "Model.py").write_bytes(b"a = 1\n")
        if (root / "pkg" / "model.py").exists():
            wc, _, _ = props_from("### EDIT: pkg/model.py\n<<<<<<< SEARCH\na = 1\n=======\na = 2\n>>>>>>> REPLACE\n")
            with contextlib.redirect_stdout(quiet):
                fresh_applier().apply(fresh_applier().validate(wc), {"source": "selftest"})
            check("wrong-case path edits the real file and keeps its on-disk name",
                  "Model.py" in os.listdir(root / "pkg")
                  and (root / "pkg" / "Model.py").read_bytes() == b"a = 2\n")
        (root / "pkg" / "Model.py").unlink()
    except Exception as exc:
        check("self-test ran to completion", False, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\nkimicli self-test  (python {sys.version.split()[0]}, {sys.platform})\n")
    for name, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail and not ok else ""))
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} of {len(results)} passed."
          + ("" if not failed else "  DO NOT use --apply-fixes until every check passes."))
    return 1 if failed else 0


# ==========================================================================
# CLI
# ==========================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kimicli.py",
        description="Kimi K3 workbench: streams, saves everything, and never lets the model "
                    "write to your repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python kimicli.py --selftest
  python kimicli.py --balance
  python kimicli.py --prompt task.md --request-code
  python kimicli.py --resume last --prompt followup.md --request-code
  python kimicli.py --apply-fixes last --dry-run
  python kimicli.py --apply-fixes last --allow-new-files
  python kimicli.py --apply-fixes 20260921_101500_ab12cd --turn 2
  python kimicli.py --history
  python kimicli.py --undo last
""")

    g = p.add_argument_group("what to ask")
    g.add_argument("--prompt", help="prompt text, or a path to a .txt/.md file")
    g.add_argument("--playbook", help="inject a prompt from the playbook, e.g. P0, P3, P4")
    g.add_argument("--playbook-list", action="store_true", help="list playbook prompts and exit")
    g.add_argument("--playbook-file", default=str(PROJECT_ROOT / "AA_PROMPT_PLAYBOOK.md"))
    g.add_argument("--chat", action="store_true", help="stay interactive after the first answer")
    g.add_argument("--resume", metavar="ID", help="continue a saved session ('last' for newest)")
    g.add_argument("--request-code", action="store_true",
                   help="append the strict EDIT/FILE output contract")

    g = p.add_argument_group("context")
    g.add_argument("--codebase", default=str(DEFAULT_CODEBASE), help=f"repo dump (default: {DEFAULT_CODEBASE})")
    g.add_argument("--no-codebase", action="store_true")
    g.add_argument("--exclude", action="append", default=[], metavar="DIR",
                   help="drop files under DIR from the dump, e.g. --exclude docs (repeatable)")
    g.add_argument("--attach", action="append", default=[], metavar="PATH", help="repeatable")
    g.add_argument("--todo", help="path to AA_MASTER_TODO.md (auto-detected in the project root)")
    g.add_argument("--no-todo", action="store_true")
    g.add_argument("--memory", action="store_true", help="include .kimi_out/memory.md")
    g.add_argument("--predict", metavar="PATH",
                   help="Predicted Output: pass this file's current content as the expected "
                        "shape of the answer. Speeds up whole-file rewrites with small changes.")

    g = p.add_argument_group("model")
    g.add_argument("--model", default=MODEL)
    g.add_argument("--effort", choices=["low", "high", "max"], default="max",
                   help="reasoning effort (default max, which is also Kimi's default)")
    g.add_argument("--max-completion", type=int, default=DEFAULT_MAX_COMPLETION,
                   help=f"max output tokens (default {DEFAULT_MAX_COMPLETION:,}, ceiling 1,048,576)")
    g.add_argument("--cache-key", help="prompt_cache_key override (default: hash of the dump)")
    g.add_argument("--show-thinking", action="store_true",
                   help="print reasoning live (it is always saved to thinking.md regardless)")

    g = p.add_argument_group("money")
    g.add_argument("--balance", action="store_true", help="check account balance and exit")
    g.add_argument("--stats", action="store_true", help="spend so far, from the ledger")
    g.add_argument("--max-spend", type=float, default=8.0,
                   help="refuse to send if the worst case exceeds this many dollars (default 8)")
    g.add_argument("--no-count", action="store_true",
                   help="skip the exact tokenizer call in preflight (uses a local estimate)")
    g.add_argument("--estimate-only", action="store_true", help="run preflight and stop")
    g.add_argument("-y", "--yes", action="store_true", help="skip confirmations")

    g = p.add_argument_group("applying code (nothing here talks to the API)")
    g.add_argument("--apply-fixes", metavar="SESSION|FILE",
                   help="apply staged changes from a session ('last'), or parse a saved reply .md/.txt")
    g.add_argument("--dry-run", action="store_true", help="resolve, check and preview; write nothing")
    g.add_argument("--turn", type=int, action="append", metavar="N",
                   help="apply only these turns of the session (repeatable; default: every turn, "
                        "latest emission per file)")
    g.add_argument("--skip", action="append", default=[], metavar="PATH",
                   help="leave this file out of the apply (repeatable)")
    g.add_argument("--allow-new-files", action="store_true",
                   help="permit creating files that do not exist yet (off by default)")
    g.add_argument("--allow-new-dirs", action="store_true",
                   help="permit creating new directories for new files (off by default)")
    g.add_argument("--allow-shrink", action="store_true",
                   help="permit a whole-FILE rewrite that is much shorter than the original")
    g.add_argument("--allow-stale", action="store_true",
                   help="permit a whole-FILE write over a file that changed since Kimi saw it")
    g.add_argument("--skip-checks", action="store_true",
                   help="skip the undefined-name and cross-file import checks")
    g.add_argument("--accept-parse-errors", action="store_true",
                   help="apply even though part of the reply could not be parsed (not recommended)")
    g.add_argument("--undo", metavar="MANIFEST", help="revert an apply ('last' = newest not yet undone)")
    g.add_argument("--force", action="store_true",
                   help="with --undo: restore even over later edits (they are saved first)")
    g.add_argument("--history", action="store_true", help="list applies and their status")
    g.add_argument("--selftest", action="store_true",
                   help="prove parse/apply/rollback/undo on this machine in a temp folder, then exit")

    p.add_argument("--verbose", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(OUT_DIR / "kimicli.log", args.verbose)

    if args.selftest:
        return run_selftest()
    if args.playbook_list:
        list_playbook(Path(args.playbook_file))
        return 0
    if args.stats:
        print_stats()
        return 0
    if args.history:
        print_history(BACKUP_DIR)
        return 0

    # ---- offline modes -------------------------------------------------
    if args.undo:
        return undo(PROJECT_ROOT, BACKUP_DIR, args.undo, force=args.force, assume_yes=args.yes)

    if args.apply_fixes:
        token = args.apply_fixes
        session = resolve_session(token)
        if session:
            props, blocking, info = load_session_proposals(session, args.turn, args.skip)
            which = f"turn(s) {', '.join(map(str, args.turn))}" if args.turn else "all turns, latest emission per file"
            print(f"Session {session.id}: {len(props)} file change(s) selected ({which}).")
            for line in info:
                print(f"  note: {line}")
            return run_apply(props, args, blocking=blocking, session=session,
                             meta={"source": f"session {session.id}",
                                   "turns": args.turn or "all"})
        f = Path(token)
        if not f.is_file():
            print(f"No session or file named '{token}'.")
            return 1
        props, blocking, pr = proposals_from_text(read_text(f), f.name)
        skip_keys = {k for k in (_key_or_none(s) for s in args.skip) if k}
        props = [p for p in props if _key_or_none(p.raw_path) not in skip_keys]
        print(f"{f.name}: {len(pr.blocks)} block(s) in {len(props)} file(s).")
        for w in pr.warnings:
            print(f"  warning (line {w.line}): {w.message}")
        return run_apply(props, args, blocking=blocking, preview_source=f,
                         meta={"source": f"file {f.name}"})

    # ---- API modes -----------------------------------------------------
    if not API_KEY:
        print("MOONSHOT_API_KEY is not set. Put it in .env next to this script.")
        return 2
    kimi = Kimi(API_KEY, BASE_URL)

    if args.balance:
        bal = kimi.balance()
        if not bal:
            return 1
        print(f"\n  available : ${bal.get('available_balance', 0):,.4f}")
        print(f"  voucher   : ${bal.get('voucher_balance', 0):,.4f}")
        print(f"  cash      : ${bal.get('cash_balance', 0):,.4f}")
        print(f"\n  spent via this tool so far: {money(lifetime_spend())}\n")
        return 0

    args.prediction_text = None
    if args.predict:
        pp = Path(args.predict)
        if pp.exists():
            args.prediction_text = read_text(pp)
            logger.info("predicted output seeded from %s", pp.name)

    # Resume keeps the exact prefix, which is what makes turn 2 cheap.
    if args.resume:
        session = resolve_session(args.resume)
        if not session:
            print(f"No session '{args.resume}'.")
            return 1
        print(f"Resumed {session.id}: {len(session.messages)} messages, "
              f"{money(session.usage.cost)} spent so far.")
        # Reuse the key this session was opened with. Minting a fresh
        # "aa-resume-<id>" here was the bug that made every resumed turn
        # report 0% cached against a byte-identical prefix.
        args.cache_key_resolved = args.cache_key or session.cache_key
        if not args.cache_key_resolved:
            args.cache_key_resolved = f"aa-resume-{session.id}"
            print("  ! this session predates cache-key persistence; pass "
                  "--cache-key <the key turn 1 used> to reuse its cache.")
        elif not args.cache_key:
            print(f"  cache key: {args.cache_key_resolved} (reused from turn 1)")
        session.cache_key = args.cache_key_resolved
        if args.prompt:
            p = Path(args.prompt)
            if p.is_file():
                text = read_text(p)
                logger.info("prompt loaded from %s", p.name)
            else:
                text = args.prompt
                if re.search(r"\.(md|txt)$", args.prompt.strip(), re.I) and "\n" not in args.prompt:
                    print(f"  ! '{args.prompt}' looks like a file name but no such file exists here "
                          f"- it would be sent as the literal prompt text. Not sent.")
                    return 1
            if args.request_code:
                text = text + "\n\n" + CODE_CONTRACT
            session.messages.append({"role": "user", "content": text})
        elif not args.chat:
            print("Nothing to send. Add --prompt or --chat.")
            return 1
        ctx = Context(messages=session.messages, parts=[("conversation so far",
                      est_tokens("".join(str(m.get("content", "")) for m in session.messages)))],
                      cache_key=args.cache_key_resolved)
    else:
        if (args.prompt and not Path(args.prompt).is_file() and "\n" not in args.prompt
                and re.search(r"\.(md|txt)$", args.prompt.strip(), re.I)):
            print(f"'{args.prompt}' looks like a file name but no such file exists here - it would "
                  f"be sent as the literal prompt text. Not sent. (Run from the folder it is in.)")
            return 1
        ctx = build_context(args)
        if not any(m["role"] == "user" for m in ctx.messages) and not args.chat:
            print("No prompt given. Use --prompt, --playbook, or --chat.")
            return 1
        session = Session()
        session.messages = ctx.messages
        args.cache_key_resolved = ctx.cache_key
        session.cache_key = ctx.cache_key

    if args.estimate_only:
        args.yes = True          # a cost check should never prompt to send
        preflight(ctx, kimi, args)
        return 0
    if not preflight(ctx, kimi, args):
        print("Not sent.")
        return 1

    if any(m["role"] == "user" for m in session.messages):
        try:
            do_turn(kimi, session, args, label=args.playbook or "")
        except Exception:
            if not args.chat:
                return 1

    if args.chat:
        chat_loop(kimi, session, args)
    elif not session.printed_stage_summary:
        print(f"\nSession {session.id}.  Continue it with: "
              f"python kimicli.py --resume {session.id} --chat")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)