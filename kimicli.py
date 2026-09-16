#!/usr/bin/env python3
r"""
kimicli.py - Kimi K3 workbench (v2)

Design rules, in priority order:

  1. YOUR CODEBASE IS NEVER TOUCHED BY THE MODEL.
     Kimi has no tools and no filesystem access. Every file it proposes is
     written to .kimi_out/<session>/proposed/ ONLY. Nothing reaches the repo
     until you run --apply-fixes yourself, and that applier is two-pass
     all-or-nothing with backups and a working --undo.

  2. NOTHING IS LOST TO THE TERMINAL.
     Every token is appended to transcript.md as it arrives. Ctrl+C, a crash,
     or a 10,000-line answer scrolling past your VSCode buffer costs you
     nothing. The file is the record; the terminal is just a preview.

  3. NO SURPRISE BILLS.
     Streaming (so no 900s gateway timeout), no SDK auto-retries (a retried
     600k-token prompt is a second 600k-token prompt), a preflight that prints
     the cost before sending, a spend cap, and a running ledger.

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
    python kimicli.py --balance
    python kimicli.py --playbook P0 --chat
    python kimicli.py --prompt prompt_kimi.txt --request-code
    python kimicli.py --apply-fixes last --dry-run
    python kimicli.py --apply-fixes last
    python kimicli.py --undo last
"""

from __future__ import annotations

import argparse
import base64  # noqa: F401  (reserved: manifest payload encoding)
import hashlib
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


def est_tokens(text: str) -> int:
    """Local estimate. Code packs denser than prose; 3.6 chars/token is a
    closer fit for a repo dump than the usual 4.0 and errs on the high side."""
    return int(len(text) / 3.6) if text else 0


def money(x: float) -> str:
    return f"${x:,.4f}" if x < 1 else f"${x:,.2f}"


def cost_of(prompt: int, cached: int, completion: int) -> float:
    fresh = max(prompt - cached, 0)
    return (cached * PRICE_IN_CACHED + fresh * PRICE_IN_FRESH + completion * PRICE_OUT) / 1e6


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def atomic_write(path: Path, content: str, newline: str = "\n") -> None:
    """Write via a temp file in the same directory, then replace. A crash
    mid-write can never leave a half-written source file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".kimitmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(content)
    os.replace(tmp, path)


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

    # -- staged files ------------------------------------------------
    def stage(self, rel_path: str, content: str) -> Path:
        cleaned = re.sub(r"[^A-Za-z0-9._/\\-]", "_", rel_path).replace("\\", "/")
        # Drop '..' and drive letters: staging must never escape the session dir.
        parts = [seg for seg in cleaned.split("/") if seg not in ("", ".", "..") and ":" not in seg]
        safe = "/".join(parts) or "unnamed"
        dest = self.dir / "proposed" / safe
        dest.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(dest, content)
        return dest

    def record_proposals(self, proposals: List[Tuple[str, str]]) -> None:
        index = self.dir / "proposals.json"
        existing = json.loads(read_text(index)) if index.exists() else []
        for path, content in proposals:
            existing.append({
                "turn": self.turn,
                "path": path,
                "sha256": sha256(content),
                "lines": content.count("\n") + 1,
                "staged": str(self.stage(path, content).relative_to(self.dir)),
            })
        atomic_write(index, json.dumps(existing, indent=1))

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
    return Session(token) if (OUT_DIR / token).exists() else None


# ==========================================================================
# Response parsing: '### FILE: path' blocks
# ==========================================================================

FILE_BLOCK = re.compile(
    r"^###[ \t]*FILE:[ \t]*(?P<path>[^\n`]+?)[ \t]*\n"      # header
    r"```[A-Za-z0-9_+-]*[ \t]*\n"                            # opening fence
    r"(?P<body>.*?)"
    r"^```[ \t]*$",                                          # closing fence
    re.DOTALL | re.MULTILINE,
)


def parse_file_blocks(text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for m in FILE_BLOCK.finditer(text):
        path = m.group("path").strip().strip("`").strip()
        body = m.group("body")
        if path:
            out.append((path, body))
    return out


# ==========================================================================
# The applier: two-pass, all-or-nothing, backed up, undoable
# ==========================================================================

ELISION = [
    re.compile(r"(?im)^\s*(?:#|//|/\*|<!--|--)?\s*\.{3,}\s*\(?\s*(?:rest|remainder|remaining|the rest|unchanged|existing|same)\b"),
    re.compile(r"(?im)\b(?:rest|remainder) of (?:the )?(?:file|function|class|code)\s+(?:is\s+)?(?:unchanged|the same|omitted|as before)"),
    re.compile(r"(?im)^\s*(?:#|//|/\*|<!--|--)?\s*(?:\.{3,}|\u2026)\s*(?:existing|previous|unchanged|other)\s+(?:code|methods|imports|content)"),
    re.compile(r"(?im)\bomitted for brevity\b"),
    re.compile(r"(?im)^\s*(?:#|//)\s*\.{3,}\s*$"),
]


@dataclass
class Plan:
    path: str
    target: Optional[Path]
    content: str
    action: str = "update"           # update | create
    problems: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    old_lines: int = 0
    new_lines: int = 0


class Applier:
    def __init__(self, root: Path, allow_new: bool = False, shrink_ratio: float = 0.6,
                 allow_shrink: bool = False):
        self.root = root.resolve()
        self.allow_new = allow_new
        self.shrink_ratio = shrink_ratio
        self.allow_shrink = allow_shrink

    # -- path safety -------------------------------------------------
    def _is_protected(self, target: Path) -> bool:
        try:
            rel = target.relative_to(self.root)
        except ValueError:
            return True
        parts = set(rel.parts) | {rel.name}
        return any(p in parts for p in PROTECTED)

    def secure_resolve(self, raw: str) -> Optional[Path]:
        raw = raw.strip().strip('"').strip("'")
        if not raw or raw in (".", ".."):
            return None
        normalised = raw.replace("\\", "/")
        # An absolute, UNC or drive-qualified path from the model is always
        # refused. Check BEFORE stripping leading slashes, or '//server/share'
        # silently becomes the relative path 'server/share'.
        if normalised.startswith("//") or re.match(r"^[A-Za-z]:", normalised):
            return None
        cleaned = normalised.lstrip("/")
        candidate = (self.root / cleaned)
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self.root)
        except (ValueError, OSError):
            return None
        # Refuse if any existing parent is a symlink escaping the root.
        probe = resolved
        while probe != self.root and probe.parent != probe:
            if probe.is_symlink():
                try:
                    probe.resolve().relative_to(self.root)
                except ValueError:
                    return None
            probe = probe.parent
        return resolved

    def locate(self, raw: str) -> Tuple[Optional[Path], str]:
        """Exact match wins. Otherwise a unique tail-match. Never guess."""
        direct = self.secure_resolve(raw)
        if direct and direct.exists():
            return direct, "exact"
        wanted = Path(raw.replace("\\", "/"))
        name = wanted.name
        if not name:
            return None, "no filename"
        candidates = [
            p for p in self.root.rglob(name)
            if p.is_file() and not any(part.startswith(".") or part in PROTECTED for part in p.parts)
        ]
        if len(wanted.parts) > 1 and len(candidates) > 1:
            tail = "/".join(wanted.parts[-2:]).lower()
            narrowed = [p for p in candidates if str(p).replace("\\", "/").lower().endswith(tail)]
            if narrowed:
                candidates = narrowed
        if len(candidates) == 1:
            return candidates[0], f"matched {candidates[0].relative_to(self.root)}"
        if len(candidates) > 1:
            names = ", ".join(str(c.relative_to(self.root)) for c in candidates[:4])
            return None, f"ambiguous ({len(candidates)} matches: {names})"
        return direct, "new file"

    # -- pass 1: validate, write nothing ------------------------------
    def validate(self, proposals: Iterable[Tuple[str, str]]) -> List[Plan]:
        plans: List[Plan] = []
        seen: Dict[str, int] = {}
        for raw, content in proposals:
            target, how = self.locate(raw)
            plan = Plan(path=raw, target=target, content=content)
            plan.new_lines = content.count("\n") + 1

            if target is None:
                plan.problems.append(f"cannot resolve path ({how})")
                plans.append(plan)
                continue
            if self._is_protected(target):
                plan.problems.append("refused: protected path (git/venv/env/tooling)")
                plans.append(plan)
                continue
            if how.startswith("matched"):
                plan.notes.append(how)

            key = str(target).lower()
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                plan.problems.append("the same file is proposed twice in one response")

            if target.exists():
                if not target.is_file():
                    plan.problems.append("target exists and is not a regular file")
                else:
                    old = read_text(target)
                    plan.old_lines = old.count("\n") + 1
                    if old.strip() == content.strip():
                        plan.action = "identical"
                    if (not self.allow_shrink and plan.old_lines > 40
                            and plan.new_lines < plan.old_lines * self.shrink_ratio):
                        plan.problems.append(
                            f"content shrank {plan.old_lines} -> {plan.new_lines} lines "
                            f"(< {int(self.shrink_ratio * 100)}%); looks truncated. "
                            f"--allow-shrink to override")
            else:
                plan.action = "create"
                if not self.allow_new:
                    plan.problems.append("new file; --allow-new-files to permit")

            if not content.strip():
                plan.problems.append("empty content")

            for pat in ELISION:
                m = pat.search(content)
                if m:
                    line = content[:m.start()].count("\n") + 1
                    plan.problems.append(
                        f"elision marker at line {line}: {m.group(0).strip()[:60]!r} "
                        f"- this file is a summary, not a whole file")
                    break

            if target.suffix == ".py":
                try:
                    compile(content, str(target), "exec")
                except SyntaxError as exc:
                    plan.problems.append(f"python syntax error at line {exc.lineno}: {exc.msg}")
            elif target.suffix == ".json":
                try:
                    json.loads(content)
                except Exception as exc:
                    plan.problems.append(f"invalid JSON: {exc}")

            plans.append(plan)
        return plans

    # -- pass 2: write --------------------------------------------------
    def apply(self, plans: List[Plan], dry_run: bool) -> Dict[str, Any]:
        manifest_id = uuid.uuid4().hex[:8]
        manifest: Dict[str, Any] = {
            "id": manifest_id,
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "root": str(self.root),
            "dry_run": dry_run,
            "files": [],
        }
        backup_root = BACKUP_DIR / manifest_id
        for plan in plans:
            assert plan.target is not None
            rel = plan.target.relative_to(self.root)
            entry: Dict[str, Any] = {
                "path": str(rel).replace("\\", "/"),
                "action": plan.action,
                "backup": None,
                "sha256_before": None,
                "sha256_after": sha256(plan.content),
                "lines_before": plan.old_lines,
                "lines_after": plan.new_lines,
            }
            if plan.action == "identical":
                entry["action"] = "identical"
                manifest["files"].append(entry)
                print(f"  [have] {rel}  (already identical)")
                continue

            newline = "\n"
            if plan.target.exists():
                raw = plan.target.read_bytes()
                entry["sha256_before"] = hashlib.sha256(raw).hexdigest()
                if b"\r\n" in raw:
                    newline = "\r\n"
                backup = backup_root / rel
                entry["backup"] = str(backup.relative_to(BACKUP_DIR)).replace("\\", "/")
                if not dry_run:
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(plan.target, backup)

            if dry_run:
                print(f"  [dry ] {plan.action:8} {rel}  ({plan.old_lines} -> {plan.new_lines} lines)")
            else:
                atomic_write(plan.target, plan.content, newline=newline)
                print(f"  [ok  ] {plan.action:8} {rel}  ({plan.old_lines} -> {plan.new_lines} lines)")
            manifest["files"].append(entry)

        manifest_path = BACKUP_DIR / f"manifest_{manifest_id}.json"
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write(manifest_path, json.dumps(manifest, indent=2))
        return manifest

    # -- undo -------------------------------------------------------
    def undo(self, manifest_id: str) -> None:
        path = (BACKUP_DIR / f"manifest_{manifest_id}.json")
        if not path.exists():
            candidates = sorted(BACKUP_DIR.glob("manifest_*.json"))
            if manifest_id == "last" and candidates:
                path = max(candidates, key=lambda p: p.stat().st_mtime)
            else:
                print(f"No manifest '{manifest_id}'. Available: "
                      f"{', '.join(c.stem.replace('manifest_', '') for c in candidates) or '(none)'}")
                return
        manifest = json.loads(read_text(path))
        if manifest.get("dry_run"):
            print("That manifest was a dry run; nothing was written, nothing to undo.")
            return

        restore, remove, refuse = [], [], []
        for entry in manifest["files"]:
            target = self.root / entry["path"]
            if entry["action"] == "identical":
                continue
            if target.exists():
                current = hashlib.sha256(target.read_bytes()).hexdigest()
                if current != entry["sha256_after"]:
                    refuse.append(entry["path"])
                    continue
            (restore if entry["backup"] else remove).append(entry)

        print(f"\nUndo {manifest['id']} ({manifest['created']}):")
        for e in restore:
            print(f"  restore  {e['path']}")
        for e in remove:
            print(f"  delete   {e['path']}  (was created by this apply)")
        for p in refuse:
            print(f"  SKIP     {p}  - changed since the apply; refusing to overwrite your edits")
        if not restore and not remove:
            print("  nothing to do.")
            return
        if not confirm("Proceed?"):
            print("Cancelled.")
            return
        for e in restore:
            shutil.copy2(BACKUP_DIR / e["backup"], self.root / e["path"])
        for e in remove:
            tgt = self.root / e["path"]
            if tgt.exists():
                tgt.unlink()
        print("Undo complete.")


def run_apply(proposals: List[Tuple[str, str]], args: argparse.Namespace) -> int:
    """The whole point: pass 1 decides, pass 2 executes, or nothing happens."""
    applier = Applier(PROJECT_ROOT, allow_new=args.allow_new_files,
                      allow_shrink=args.allow_shrink)
    if not proposals:
        print("No '### FILE:' blocks found in that response.")
        return 1

    print(f"\nPASS 1 - validating {len(proposals)} proposed file(s). Nothing is written.\n")
    plans = applier.validate(proposals)
    bad = [p for p in plans if p.problems]
    for p in plans:
        mark = "FAIL" if p.problems else ("same" if p.action == "identical" else p.action.upper())
        print(f"  [{mark:^6}] {p.path}")
        for n in p.notes:
            print(f"            note: {n}")
        for prob in p.problems:
            print(f"            !! {prob}")

    if bad:
        print(f"\nVALIDATION FAILED - {len(bad)} of {len(plans)} file(s) rejected. "
              f"No files were modified.")
        return 1

    print(f"\nPASS 1 clean: {len(plans)} file(s) OK.")
    if args.dry_run:
        print("\nPASS 2 - DRY RUN, still writing nothing:\n")
        applier.apply(plans, dry_run=True)
        print("\nDry run complete. Re-run without --dry-run to apply.")
        return 0

    changed = [p for p in plans if p.action != "identical"]
    if changed and not args.yes:
        print()
        if not confirm(f"Write {len(changed)} file(s) to {PROJECT_ROOT}? (backups are taken)"):
            print("Cancelled. Nothing was modified.")
            return 1
    print("\nPASS 2 - writing:\n")
    manifest = applier.apply(plans, dry_run=False)
    print(f"\nDone. Manifest {manifest['id']}. To revert:  python kimicli.py --undo {manifest['id']}")
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
Your files are applied by a two-pass all-or-nothing script. It imposes hard limits:

- It CANNOT create a file whose basename already exists elsewhere in the repo
  (__init__.py, base.py, conftest.py). If a stage needs one, say so as a manual
  step - "create the empty file first" - and do not emit it as a FILE block.
- It CANNOT delete files. Propose deletions as a `git rm` line for the human to run.
- It REJECTS a file that shrinks below 60% of its current line count. If a change
  removes that much, say so explicitly before the block so the human passes --allow-shrink.
- One rejected file rejects the ENTIRE batch. Prefer fewer, smaller, surer files.
"""

CODE_CONTRACT = """\
OUTPUT CONTRACT FOR CODE - this is parsed by a script, so it is strict:

For every file you want changed, emit exactly:

### FILE: relative/path/from/repo/root.py
```python
<the complete file, first line to last>
```

Rules that are not negotiable:
1. COMPLETE FILES ONLY. Never write "... rest unchanged", "existing code here", \
"omitted for brevity", or any ellipsis standing in for code. A validator rejects the \
entire batch when it sees one, and nothing gets applied.
2. If a file is too large to reproduce in full, DO NOT ELIDE. Say so, and propose a \
smaller change to a smaller file instead.
3. Relative paths from the repo root only. No absolute paths, no C:\\ paths, no ../.
4. Put explanation OUTSIDE the file blocks - before or after, never inside as commentary.
5. List every file you are about to emit, before the first block, with one line each \
saying what changes and why.
6. Prefer the smallest set of files that does the job."""


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
        user_chunks.append(f"<attachment name=\"{p.name}\">\n{body}\n</attachment>")
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
    n_in = exact or est

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

    proposals = parse_file_blocks(result["content"])
    if proposals:
        session.record_proposals(proposals)
        print(f"\n\n[{len(proposals)} file block(s) staged in {session.dir / 'proposed'}]")
        for path, body in proposals:
            print(f"   - {path}  ({body.count(chr(10)) + 1} lines)")
        print(f"\n   Review, then:  python kimicli.py --apply-fixes {session.id} --dry-run")

    print_turn_summary(result, session)
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
  /files           list the file blocks staged this session
  /apply           run the dry-run applier on this session
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
                idx = session.dir / "proposals.json"
                if idx.exists():
                    for row in json.loads(read_text(idx)):
                        print(f"  turn {row['turn']}: {row['path']} ({row['lines']} lines)")
                else:
                    print("  no file blocks staged yet")
                continue
            if cmd == "/apply":
                props = load_session_proposals(session)
                ns = argparse.Namespace(dry_run=True, allow_new_files=args.allow_new_files,
                                        allow_shrink=args.allow_shrink, yes=False)
                run_apply(props, ns)
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
            chunks.append(f"<attachment name=\"{p.name}\">\n{read_text(p)}\n</attachment>")
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


def load_session_proposals(session: Session) -> List[Tuple[str, str]]:
    """Latest staged version of each proposed file, in first-seen order."""
    idx = session.dir / "proposals.json"
    if not idx.exists():
        return []
    latest: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in json.loads(read_text(idx)):
        if row["path"] not in latest:
            order.append(row["path"])
        latest[row["path"]] = row
    out: List[Tuple[str, str]] = []
    for path in order:
        staged = session.dir / latest[path]["staged"]
        if staged.exists():
            out.append((path, read_text(staged)))
    return out


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
# CLI
# ==========================================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kimicli.py",
        description="Kimi K3 workbench: streams, saves everything, and never lets the model "
                    "write to your repo.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python kimicli.py --balance
  python kimicli.py --playbook P0 --chat
  python kimicli.py --prompt prompt_kimi.txt --request-code --exclude docs
  python kimicli.py --resume last --chat
  python kimicli.py --apply-fixes last --dry-run
  python kimicli.py --apply-fixes last
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
                   help="append the strict '### FILE:' output contract")

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
                   help="apply staged files from a session ('last'), or parse a response .md/.txt")
    g.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    g.add_argument("--allow-new-files", action="store_true",
                   help="permit creating files that do not exist yet (off by default)")
    g.add_argument("--allow-shrink", action="store_true",
                   help="permit a rewrite that is much shorter than the original")
    g.add_argument("--undo", metavar="MANIFEST", help="revert an apply ('last' for the most recent)")

    p.add_argument("--verbose", action="store_true")
    return p


def main() -> int:
    args = build_parser().parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(OUT_DIR / "kimicli.log", args.verbose)

    if args.playbook_list:
        list_playbook(Path(args.playbook_file))
        return 0
    if args.stats:
        print_stats()
        return 0

    # ---- offline modes -------------------------------------------------
    if args.undo:
        Applier(PROJECT_ROOT).undo(args.undo)
        return 0

    if args.apply_fixes:
        token = args.apply_fixes
        session = resolve_session(token)
        if session:
            proposals = load_session_proposals(session)
            print(f"Session {session.id}: {len(proposals)} staged file(s).")
        else:
            f = Path(token)
            if not f.exists():
                print(f"No session or file named '{token}'.")
                return 1
            proposals = parse_file_blocks(read_text(f))
            print(f"{f.name}: {len(proposals)} file block(s) found.")
        return run_apply(proposals, args)

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
            text = read_text(p) if (p.exists() and p.is_file()) else args.prompt
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
    else:
        print(f"\nSession {session.id}.  Continue it with: "
              f"python kimicli.py --resume {session.id} --chat")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
