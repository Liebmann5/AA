"""Domain memory (CT-ALG-020, 06 s10; CT-FR-025) and the view catalog beside it.

An accelerator, never authority (CT-INV-012). An entry is a *hint*
(strategy ids, parameter deltas) plus the *expectations* its output must
meet (record-count range, title-link bijection, a field set). The rules:

* key = (registrable domain, region-skeleton hash at depth 3, classes excluded);
* used only when the general method abstains or overruns its budget, or the
  resource profile selects the fast path;
* **verified on every use** against its expectations and the global
  invariants: pass → ``uses += 1``; fail → ``failures += 1``; at 2 failures
  the entry is quarantined (moved to ``retired``, never silently deleted);
* absolute expiry (default 30 days); renewal only after 3 verified passes;
* capacity cap (default 2,000) with LRU eviction, every eviction logged;
* the snapshot hash goes into the run record so a replay uses the same memory.

Time is injected (``now``, seconds); the store is plain data with
``to_json``/``from_json``. The caller decides where it lives (AA's data dir,
or a USB stick) and when it is written.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from pagecomp.doc import ELEMENT, FRAME, SHADOW, Doc
from pagecomp.links import site

DAY = 86_400.0


def region_hash(doc: Doc, root: int = 0, depth: int = 3) -> str:
    """Skeleton hash of a region: tag paths to ``depth``, no classes, no text.

    Two loads of one template (different postings, different class hashes)
    share it; a redesign does not."""
    h = hashlib.sha256()
    base = doc.depth[root]
    j, stop = root, doc.end[root]
    while j < stop:
        k = doc.kind[j]
        if k in (ELEMENT, SHADOW, FRAME):
            if doc.depth[j] - base > depth:
                j = doc.end[j]
                continue
            h.update(f"{doc.depth[j] - base}:{doc.tag_name(j)};".encode())
        j += 1
    return h.hexdigest()[:16]


@dataclass(frozen=True)
class Expectations:
    min_records: int = 0
    max_records: int = 10_000
    title_link_bijection: bool = False
    fields: tuple[str, ...] = ()


@dataclass
class Entry:
    domain: str
    region: str
    hint: dict[str, Any]
    expect: Expectations
    created: float
    expires: float
    uses: int = 0
    failures: int = 0
    passes_since_renewal: int = 0
    last_used: float = 0.0
    note: str = ""


@dataclass
class MemoryEvent:
    kind: str      # stored | used-pass | used-fail | quarantined | expired | evicted | renewed
    key: str
    at: float


def check_expectations(expect: Expectations, output: Mapping[str, Any]) -> tuple[bool, str]:
    """``output``: ``records`` (count), ``titles`` and ``links`` (lists), ``fields`` (names present)."""
    n = int(output.get("records", 0))
    if not expect.min_records <= n <= expect.max_records:
        return False, f"record count {n} outside [{expect.min_records}, {expect.max_records}]"
    if expect.title_link_bijection:
        titles, links_ = output.get("titles", []), output.get("links", [])
        if len(titles) != len(links_) or len(set(links_)) != len(links_) or not all(titles):
            return False, "titles and links are not one-to-one"
    missing = set(expect.fields) - set(output.get("fields", ()))
    if missing:
        return False, "missing fields: " + ",".join(sorted(missing))
    return True, ""


@dataclass
class DomainMemory:
    capacity: int = 2000
    ttl_days: float = 30.0
    quarantine_after: int = 2
    renew_after: int = 3
    entries: "OrderedDict[str, Entry]" = field(default_factory=OrderedDict)
    retired: dict[str, Entry] = field(default_factory=dict)
    log: list[MemoryEvent] = field(default_factory=list)
    max_log: int = 5000

    @staticmethod
    def key(domain_or_host: str, region: str) -> str:
        return f"{site(domain_or_host)}|{region}"

    def _event(self, kind: str, key: str, now: float) -> None:
        self.log.append(MemoryEvent(kind, key, now))
        if len(self.log) > self.max_log:
            del self.log[: len(self.log) - self.max_log]

    def store(self, host: str, region: str, hint: Mapping[str, Any], expect: Expectations, now: float,
              note: str = "") -> str:
        k = self.key(host, region)
        self.entries[k] = Entry(site(host), region, dict(hint), expect, now, now + self.ttl_days * DAY,
                                last_used=now, note=note)
        self.entries.move_to_end(k)
        self._event("stored", k, now)
        while len(self.entries) > self.capacity:
            old, _ = self.entries.popitem(last=False)
            self._event("evicted", old, now)
        return k

    def lookup(self, host: str, region: str, now: float) -> Entry | None:
        """A live entry or None. Expired entries are retired on sight."""
        k = self.key(host, region)
        e = self.entries.get(k)
        if e is None:
            return None
        if now >= e.expires:
            self.retired[k] = self.entries.pop(k)
            self._event("expired", k, now)
            return None
        self.entries.move_to_end(k)
        return e

    def use(self, host: str, region: str, now: float, run: Callable[[Mapping[str, Any]], Mapping[str, Any]],
            ) -> tuple[Mapping[str, Any] | None, str]:
        """Apply the hint through ``run`` and verify the output. Returns the
        output only when it passes; otherwise ``(None, reason)`` and the
        caller falls back to the general method."""
        e = self.lookup(host, region, now)
        if e is None:
            return None, "no-entry"
        k = self.key(host, region)
        out = run(e.hint)
        ok, why = check_expectations(e.expect, out)
        e.last_used = now
        if ok:
            e.uses += 1
            e.passes_since_renewal += 1
            self._event("used-pass", k, now)
            if e.passes_since_renewal >= self.renew_after:
                e.expires = now + self.ttl_days * DAY
                e.passes_since_renewal = 0
                self._event("renewed", k, now)
            return out, ""
        e.failures += 1
        self._event("used-fail", k, now)
        if e.failures >= self.quarantine_after:
            self.retired[k] = self.entries.pop(k)
            self._event("quarantined", k, now)
        return None, why

    def snapshot_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()[:16]

    def to_json(self) -> str:
        def enc(e: Entry) -> dict[str, Any]:
            d = asdict(e)
            d["expect"] = asdict(e.expect)
            return d
        return json.dumps({"v": 1, "entries": [[k, enc(e)] for k, e in self.entries.items()],
                           "retired": [[k, enc(e)] for k, e in sorted(self.retired.items())]},
                          sort_keys=True, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str, **kw: Any) -> "DomainMemory":
        mem = cls(**kw)
        try:
            data = json.loads(text)
        except ValueError:
            return mem
        if not isinstance(data, dict) or data.get("v") != 1:
            return mem

        def dec(d: dict[str, Any]) -> Entry | None:
            try:
                raw: dict[str, Any] = {k: (tuple(v) if isinstance(v, list) else v)
                                       for k, v in d.pop("expect").items()}
                exp = Expectations(**raw)
                return Entry(expect=exp, **d)
            except (TypeError, KeyError, AttributeError):
                return None
        for k, d in data.get("entries", [])[: mem.capacity]:
            e = dec(dict(d))
            if e is not None:
                mem.entries[k] = e
        for k, d in data.get("retired", []):
            e = dec(dict(d))
            if e is not None:
                mem.retired[k] = e
        return mem


def with_hint(e: Entry, **changes: Any) -> Entry:
    return replace(e, **changes)
