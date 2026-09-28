"""Identity pins: who is allowed to compute an identity, and with which scheme.

This project carries three unrelated notions of "which company is this", and
two unrelated notions of "which thing is this page". They have already drifted
apart once without anyone noticing, so these pins enumerate every site that
mints one, and fail when a new one appears.

The three company identities, all real and all correct in their own lane:

  RESEARCH    a salted digest of the company name, written to the ``company_id``
              column of ``research_signals`` and ``application_outcomes``.
              ONE SCHEME since item 4a — HMAC-SHA256, minted only in
              domain/services/research_identity.py; see the ratchet below.
  THROTTLING  the RAW company name, used by ``throttling_filter`` for the
              per-company cap and cooldown. Must never be hashed: the cap is
              a user-facing promise, not a research measurement.
  PERSISTENCE whatever the repository uses for its own keys.

The two page identities:

  STRUCTURAL  ``structural_hashing`` / ``math_dom`` hash a ``DOMNode`` shape.
              This is the math subsystem's notion of "same layout".
  POSTING     a content hash of (title, company, normalised description),
              documented by ``job_lifecycle_tracker`` and read in two
              workflows. NOTHING HAS EVER COMPUTED IT — see the ratchet below.

Four instruments, honestly labelled:

  RATCHET  test_research_company_identity_sites
  RATCHET  test_posting_identity_sites
  RATCHET  test_hash_families_stay_disjoint
           Each asserts the CURRENT inventory exactly. A new site fails; so
           does removing one without updating the map, which is the point —
           the inventory moves on purpose, in the change that moves it.

  TEETH    test_research_company_identity_has_one_definition
           Carried ``xfail(strict=True)`` until item 4a landed; strict turned
           the XPASS into a failure and the marker was deleted in the change
           that collapsed the two schemes. Now live and must stay live.
  TEETH    test_posting_identity_has_exactly_one_definition
           Still asserts the END state and still FAILS TODAY, so it keeps its
           ``xfail(strict=True)``. Strict matters: when the work lands, it
           XPASSes, pytest turns an unexpected pass into a failure, and the
           change that fixed the defect is forced to delete its own marker.
           A pin that can be silently outgrown is not a pin.

  TEETH    test_throttling_filter_keeps_the_raw_company_name
           Green today and must stay green. The per-company cap counts
           applications by raw name; routing it through a research hash would
           silently change how many applications a user may send.

  GUARD    test_the_identity_scan_finds_the_known_sites
  GUARD    test_the_identity_scan_no_longer_sees_the_retired_sites
           A scan that stopped finding anything would pass all three ratchets
           by accident; the retired sites must stay retired, because the day
           one of them reappears, the join key has forked again.
"""
from __future__ import annotations

import ast
import pathlib
from collections.abc import Iterator
from typing import NamedTuple

import pytest

from ._binding import (
    iter_scope,
    iter_scopes,
    name_used_outside_import,
    scope_assignments,
    top_level_bindings,
)

SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "auto_apply"

# Every stdlib call that produces a digest. A new algorithm added here is a
# deliberate act; a new algorithm NOT added here would make the scans below
# quietly blind, which is why the guard at the bottom exists.
DIGEST_CALLS = frozenset(
    {
        "hmac.new",
        "hashlib.new",
        "hashlib.md5",
        "hashlib.sha1",
        "hashlib.sha256",
        "hashlib.sha384",
        "hashlib.sha512",
        "hashlib.blake2b",
        "hashlib.blake2s",
    }
)


class IdentitySite(NamedTuple):
    """What one module does when it mints an identity.

    A typed record rather than a dict: the maps below are read far more often
    than they are written, and ``IdentitySite(sites=1, scheme="hmac-sha256",
    ...)`` says what a bare tuple would not.
    """

    sites: int
    scheme: str
    salt: str


# ── helpers ──────────────────────────────────────────────────────────────────


def _py_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py"))


def _rel(p: pathlib.Path) -> str:
    return p.relative_to(SRC).as_posix()


def _dotted(expr: ast.expr) -> str:
    """``hashlib.sha256`` for an Attribute chain, ``foo`` for a bare Name."""
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value)
        return f"{base}.{expr.attr}" if base else expr.attr
    if isinstance(expr, ast.Subscript):
        return _dotted(expr.value)
    if isinstance(expr, ast.Call):
        return _dotted(expr.func)
    return ""


def _alias_map(tree: ast.Module) -> dict[str, str]:
    """Local name → canonical dotted name, for this module's imports.

    Without this, ``from hashlib import sha256`` then ``sha256(...)`` reads as
    a call to something named ``sha256`` and slips past every scan below. The
    tree happens to use plain ``import hashlib`` everywhere today; that is a
    habit, not a guarantee, and a pin that depends on a habit is decoration.
    """
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                aliases[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            for a in node.names:
                aliases[a.asname or a.name] = f"{node.module}.{a.name}"
    return aliases


def _canonical(dotted: str, aliases: dict[str, str]) -> str:
    """Rewrite *dotted*'s head through *aliases* so ``h.sha256`` → ``hashlib.sha256``."""
    if not dotted:
        return dotted
    if dotted in aliases:
        return aliases[dotted]
    head, _, rest = dotted.partition(".")
    if head in aliases and rest:
        return f"{aliases[head]}.{rest}"
    return dotted


def _digest_calls_in(expr: ast.expr, aliases: dict[str, str]) -> list[str]:
    """Canonical dotted names of every digest call reachable inside *expr*."""
    return sorted(
        {
            _canonical(_dotted(n.func), aliases)
            for n in ast.walk(expr)
            if isinstance(n, ast.Call) and _canonical(_dotted(n.func), aliases) in DIGEST_CALLS
        }
    )


def _hmac_digestmod(expr: ast.expr, aliases: dict[str, str]) -> str:
    """The algorithm an ``hmac.new`` call was given, as written.

    ``digestmod`` arrives as a bare reference (``hashlib.sha256``, no call) or
    as a string (``"sha256"``), so walking for Call nodes never finds it —
    which is precisely the bug this helper exists to not have.
    """
    for node in ast.walk(expr):
        if not isinstance(node, ast.Call) or _canonical(_dotted(node.func), aliases) != "hmac.new":
            continue
        chosen: ast.expr | None = None
        if len(node.args) >= 3:
            chosen = node.args[2]
        for kw in node.keywords:
            if kw.arg == "digestmod":
                chosen = kw.value
        if chosen is None:
            return "unspecified"
        if isinstance(chosen, ast.Constant) and isinstance(chosen.value, str):
            return chosen.value
        dotted = _canonical(_dotted(chosen), aliases)
        return dotted.split(".", 1)[1] if dotted.startswith("hashlib.") else dotted or "unspecified"
    return "unspecified"


def _scheme_of(expr: ast.expr, aliases: dict[str, str]) -> str:
    """Name the construction, not just the algorithm.

    ``hmac.new(key, msg, hashlib.sha256)`` and ``hashlib.sha256(msg + key)``
    are both "SHA-256 with a salt" and produce completely different digests.
    Labelling them apart is the entire reason this pin caught the drift.
    """
    calls = _digest_calls_in(expr, aliases)
    if "hmac.new" in calls:
        return f"hmac-{_hmac_digestmod(expr, aliases)}"
    if len(calls) == 1:
        return f"{calls[0].split('.', 1)[1]}-concat"
    return "+".join(calls) or "none"


def _salt_source(scope: ast.AST, expr: ast.expr, aliases: dict[str, str]) -> str:
    """Where the salt in *expr* came from, resolved against *scope*'s locals.

    A site that reads ``os.environ.get(RESEARCH_SALT_ENV_VAR, ...)`` and one
    that reads ``os.environ.get("AA_RESEARCH_SALT", ...)`` agree; one that
    hard-codes a literal does not, and that is worth failing over. Uses the
    shared single-assignment resolver so a name assigned twice reports
    ``ambiguous`` rather than being guessed at.
    """
    assigned = scope_assignments(scope)
    names = {n.id for n in ast.walk(expr) if isinstance(n, ast.Name)}
    sources: set[str] = set()
    for name in sorted(names):
        value = assigned.get(name)
        if value is None:
            continue
        for call in ast.walk(value):
            if not isinstance(call, ast.Call) or _canonical(_dotted(call.func), aliases) not in {
                "os.environ.get",
                "os.getenv",
            }:
                continue
            if not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant):
                sources.add(str(first.value))
            elif isinstance(first, ast.Name):
                sources.add(f"<{first.id}>")
    if not sources:
        return "none"
    return "+".join(sorted(sources))


def _enclosing_scopes(tree: ast.Module) -> dict[int, ast.AST]:
    """Map ``id(node) -> the function that encloses it``, module if none.

    ``scope_assignments`` resolves a local against ONE scope, so a caller has
    to know which scope a call site sits in. ``iter_scopes`` yields the module
    and every function; ``iter_scope`` yields a scope's own nodes without
    descending into nested ones. Composed, they give each node exactly one
    owner — which is what stops a site being counted once per enclosing
    scope, the way a bare ``ast.walk`` per scope would.
    """
    owner: dict[int, ast.AST] = {}
    for scope in iter_scopes(tree):
        for node in iter_scope(scope):
            owner.setdefault(id(node), scope)
    return owner


def _bindings_of(
    tree: ast.Module, suffix: str, *, annotated: bool
) -> Iterator[tuple[ast.AST, ast.expr]]:
    """Yield ``(node, value)`` for every binding of a name ending *suffix*.

    Catches both shapes an identity can arrive in::

        company_id = hashlib.sha256(...).hexdigest()[:16]     # Assign
        Signal(..., company_id=hmac.new(...).hexdigest())     # keyword

    One ``ast.walk`` over the whole module, so every binding is found exactly
    once wherever it lives — module scope, a method, or a class body.

    *annotated* decides whether ``posting_hash: str | None = None`` counts.
    For a producer scan it does; for a consumer scan it does not, because a
    dataclass field declaration is the schema, not a place the value is used.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.endswith(suffix):
                    yield node, node.value
        elif isinstance(node, ast.AnnAssign) and annotated:
            if isinstance(node.target, ast.Name) and node.target.id.endswith(suffix):
                if node.value is not None:
                    yield node, node.value
        elif isinstance(node, ast.keyword) and node.arg == suffix:
            yield node, node.value


def _identity_sites(target_suffix: str) -> dict[str, IdentitySite]:
    """Every MODULE that mints *target_suffix* from a digest, and how.

    Keyed by module rather than by ``file:line`` on purpose, following the
    print-site ratchet next door: a line number turns every unrelated edit
    above the site into a pin failure, and a pin that cries wolf gets
    disabled. The scheme, the salt source and the number of sites are the
    facts worth failing over.

    A site that merely READS or FORWARDS the value carries no digest call and
    is deliberately not a site — forwarding an identity is not minting one.
    """
    found: dict[str, IdentitySite] = {}
    for path in _py_files(SRC):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - a broken file fails elsewhere
            continue
        aliases = _alias_map(tree)
        owner = _enclosing_scopes(tree)
        schemes: set[str] = set()
        salts: set[str] = set()
        count = 0
        for node, value in _bindings_of(tree, target_suffix, annotated=True):
            if not _digest_calls_in(value, aliases):
                continue
            count += 1
            schemes.add(_scheme_of(value, aliases))
            salts.add(_salt_source(owner.get(id(node), tree), value, aliases))
        if count:
            found[_rel(path)] = IdentitySite(
                sites=count,
                scheme="+".join(sorted(schemes)),
                salt="+".join(sorted(salts)),
            )
    return found


def _consumer_sites(target_suffix: str) -> dict[str, int]:
    """Modules that bind *target_suffix* WITHOUT computing it, and how often."""
    found: dict[str, int] = {}
    for path in _py_files(SRC):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        aliases = _alias_map(tree)
        count = sum(
            1
            for _node, value in _bindings_of(tree, target_suffix, annotated=False)
            if not _digest_calls_in(value, aliases)
        )
        if count:
            found[_rel(path)] = count
    return found


# ── RATCHET: who mints a research company identity ───────────────────────────
#
# ONE scheme, ONE site. Item 4a collapsed the two constructions — hmac-sha256
# (key=salt, msg=name) in the detector path and sha256(name + salt) in the
# application path — into compute_company_id in research_identity.py. Rows
# the two old schemes produced are nulled by the aggregator's one-time
# migration.
#
# The salt source reads "none" because the scan cannot follow
# resolve_research_salt() — the os.environ.get lives one call away BY DESIGN,
# so that no hashing site can ever read (or default) the salt itself. "none"
# is the assertion here, not a gap: any FUTURE site reporting a readable salt
# source has re-inlined what item 4a removed. The limit worth naming: a
# hard-coded literal salt would ALSO report "none" — the scan cannot tell
# centralised resolution from a buried literal, so read this file's diff
# whenever this map changes.
#
EXPECTED_COMPANY_IDENTITY_SITES: dict[str, IdentitySite] = {
    "domain/services/research_identity.py": IdentitySite(
        sites=1, scheme="hmac-sha256", salt="none"
    ),
}


def test_research_company_identity_sites() -> None:
    """RATCHET: the exact set of places that mint a research ``company_id``.

    One today, by construction. This asserts it exactly so a second cannot
    arrive quietly — which is how the retired sha256-concat site arrived.
    The salt source is part of the map because a site that hard-coded its
    salt would hash identically to nothing else and look perfectly fine; see
    the comment above the map for what "none" certifies and what it cannot.
    """
    actual = _identity_sites("company_id")
    assert actual == EXPECTED_COMPANY_IDENTITY_SITES, (
        "the research company-identity inventory changed.\n"
        f"  expected: {EXPECTED_COMPANY_IDENTITY_SITES}\n"
        f"  actual:   {actual}\n"
        "A new entry means a fourth company identity now exists and nothing "
        "joins to it. A removed entry is progress — update the map in the "
        "same change and say which scheme survived.\n"
        "NOTE: throttling_filter's raw-name identity is NOT in this map and "
        "must never enter it; see test_throttling_filter_keeps_the_raw_"
        "company_name."
    )


def test_research_company_identity_has_one_definition() -> None:
    """TEETH: one column, one construction, one salt source.

    ``company_id`` is a join key. Two constructions mean the join silently
    returns nothing rather than failing, which is the worst failure mode a
    research number can have.
    """
    sites = _identity_sites("company_id")
    schemes = {meta.scheme for meta in sites.values()}
    salts = {meta.salt for meta in sites.values()}
    assert len(sites) == 1, (
        f"a research company_id is minted in {len(sites)} places: {sorted(sites)}. "
        "It belongs in exactly one domain function that both the detector path "
        "and the application path call."
    )
    assert len(schemes) == 1, f"incompatible company-hash constructions in use: {sorted(schemes)}"
    assert len(salts) == 1, f"company hashing reads more than one salt source: {sorted(salts)}"


# ── RATCHET: who mints a posting identity ────────────────────────────────────
#
# ZERO. `posting_hash` is read from `job.metadata` in two workflows, forwarded
# into three observation records, and used as the deduplication key inside
# run_all_detectors — and nothing has ever written it. tests/workflows/
# test_attempt_join.py already says so in prose; this says it in an assertion.
#
EXPECTED_POSTING_IDENTITY_SITES: dict[str, IdentitySite] = {}

# The consumers, and what each one does with a value nothing has ever produced:
#   signal_aggregator        2 — forwards observation.posting_hash into two records
#   applications_workflow    2 — reads job.metadata["posting_hash"], forwards it
#   vetting_workflow         1 — passes posting_hash=None DELIBERATELY. Item 2 moved
#                                the observation here and declined to mint an identity
#                                from a description that may be a title fallback;
#                                test_posting_hash_is_none_on_every_observation in
#                                tests/workflows/test_vetting_workflow.py is the pin
#                                that holds that choice. Item 4 turns this site into
#                                the producer.
#   signal_detectors/__init__ 1 — the dedup key, so it currently dedups on None
#
# discovery_workflow was a consumer (2) until item 2 deleted its observation block.
EXPECTED_POSTING_CONSUMERS: dict[str, int] = {
    "adapters/secondary/research/signal_aggregator.py": 2,
    "application/workflows/applications_workflow.py": 2,
    "application/workflows/vetting_workflow.py": 1,
    "domain/services/signal_detectors/__init__.py": 1,
}


def test_posting_identity_sites() -> None:
    """RATCHET: nothing computes ``posting_hash``, and seven places consume it.

    Recording the consumers matters as much as recording the (empty) set of
    producers: when item 2 finally mints one, every consumer on this list has
    to be re-read to confirm it receives the real value rather than the
    ``None`` it has silently tolerated since the column was created.
    """
    producers = _identity_sites("posting_hash")
    consumers = _consumer_sites("posting_hash")
    assert producers == EXPECTED_POSTING_IDENTITY_SITES, (
        "the posting-identity producer inventory changed.\n"
        f"  expected: {EXPECTED_POSTING_IDENTITY_SITES}\n"
        f"  actual:   {producers}\n"
        "If this is item 2 landing: good. Update the map, then delete the "
        "xfail marker on test_posting_identity_has_exactly_one_definition, "
        "and confirm every consumer below now receives a real value."
    )
    assert consumers == EXPECTED_POSTING_CONSUMERS, (
        "the posting-identity consumer inventory changed.\n"
        f"  expected: {EXPECTED_POSTING_CONSUMERS}\n"
        f"  actual:   {consumers}\n"
        "A new consumer of a value that is always None is new dead weight. "
        "Update the map in the same change."
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "posting_hash has never been computed anywhere. Item 4a ruled the "
        "basis — (title, company, normalised description body), specified in "
        "that call's Part B — but deferred minting until the "
        "stability/distinctness check in the ruling has been run against "
        "real pages: the basis is settled, the evidence for it is not. When "
        "minting lands in research_identity.compute_posting_hash this "
        "XPASSes, strict turns that into a failure, and this marker must be "
        "deleted in the same change."
    ),
)
def test_posting_identity_has_exactly_one_definition() -> None:
    """TEETH: one producer, living in the domain, exporting a named function.

    Two things are asserted together because they fail together: that a
    producer exists at all, and that it is a domain function rather than a
    hash inlined into a workflow. Inlining is how the company identity came
    to have two constructions.
    """
    producers = _identity_sites("posting_hash")
    assert len(producers) == 1, (
        f"posting_hash is minted in {len(producers)} places: {sorted(producers)}. "
        "It is a join key across discovery, vetting and application; it needs "
        "exactly one definition."
    )
    module = SRC / "domain" / "services" / "research_identity.py"
    assert module.exists(), (
        "the posting identity is computed somewhere other than "
        "domain/services/research_identity.py. A join key that three layers "
        "read belongs in the domain, not inside whichever workflow happened "
        "to need it first."
    )
    exported = top_level_bindings(module)
    assert "compute_posting_hash" in exported, (
        "posting_identity.py does not export compute_posting_hash; "
        f"it binds {sorted(exported)}"
    )


# ── RATCHET: the two hash families stay apart ────────────────────────────────
#
# STRUCTURAL hashes a DOM shape and answers "is this the same layout". POSTING
# hashes text and answers "is this the same advert". job_lifecycle_tracker's
# docstring points at structural_hashing.py for a value that must be the
# second kind, which is exactly the confusion this pin exists to prevent from
# becoming code. A module that computes both families is where they merge.
#
EXPECTED_DIGEST_MODULES: dict[str, list[str]] = {
    "adapters/secondary/persistence/database.py": ["hashlib.sha256"],
    "adapters/secondary/research/research_exporter.py": ["hashlib.sha256"],
    "adapters/secondary/research/signal_aggregator.py": ["hashlib.sha256"],
    "adapters/secondary/security/data_protection.py": ["hashlib.sha256"],
    "application/services/data_processing/deduplication_manager.py": ["hashlib.md5"],
    "application/workflows/applications_workflow.py": ["hashlib.sha256"],
    "domain/models/math_dom.py": ["hashlib.md5"],
    "domain/models/timing.py": ["hashlib.sha256"],
    "domain/services/research_identity.py": ["hmac.new"],
    "domain/services/signal_detectors/__init__.py": ["hashlib.sha256"],
    "domain/services/structural_hashing.py": ["hashlib.md5"],
}


def _digest_modules() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _py_files(SRC):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        aliases = _alias_map(tree)
        calls = sorted(
            {
                _canonical(_dotted(n.func), aliases)
                for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and _canonical(_dotted(n.func), aliases) in DIGEST_CALLS
            }
        )
        if calls:
            found[_rel(path)] = calls
    return found


def test_hash_families_stay_disjoint() -> None:
    """RATCHET: the exact inventory of modules that compute any digest.

    Ten today. This is the widest net in the file and the cheapest one to
    read: any new hashing anywhere in ``src`` shows up here first, before the
    narrower pins above have to decide what it is.
    """
    actual = _digest_modules()
    assert actual == EXPECTED_DIGEST_MODULES, (
        "the set of modules that compute a digest changed.\n"
        f"  new:     { {k: v for k, v in actual.items() if k not in EXPECTED_DIGEST_MODULES} }\n"
        f"  cleared: { {k: v for k, v in EXPECTED_DIGEST_MODULES.items() if k not in actual} }\n"
        f"  changed: { {k: (EXPECTED_DIGEST_MODULES[k], v) for k, v in actual.items() if k in EXPECTED_DIGEST_MODULES and EXPECTED_DIGEST_MODULES[k] != v} }\n"
        "Adding a hash is fine. Adding it without saying which identity it "
        "mints is how this codebase ended up with two company_ids."
    )


# ── TEETH: the throttling identity is the raw name, and stays that way ───────

THROTTLING = SRC / "domain" / "vetting" / "throttling_filter.py"

# Symbols that would mean the per-company cap had been re-pointed at a
# research identity. The salt names are checked as strings because importing
# them is the regression.
FORBIDDEN_IN_THROTTLING = ("hashlib", "hmac", "posting_identity", "RESEARCH_SALT_ENV_VAR")


def test_throttling_filter_keeps_the_raw_company_name() -> None:
    """TEETH: the per-company cap counts by raw name, not by any digest.

    ``count_applications_for_company`` and ``get_last_applied_date`` take the
    company name the user would recognise. Collapsing the two research hashes
    (item 4) must not reach in here: a salted digest would silently re-bucket
    every historical application and change how many a user is allowed to
    send. This is a user-facing promise, and it outranks research tidiness in
    this project's priority order.
    """
    source = THROTTLING.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)

    offenders = sorted(
        symbol
        for symbol in FORBIDDEN_IN_THROTTLING
        if any(symbol in mod for mod in imported) or name_used_outside_import(tree, symbol)
    )
    assert not offenders, (
        "throttling_filter now reaches for hashing or research-salt machinery: "
        f"{offenders}. The per-company cap must keep counting on the raw "
        "company name; anonymising it changes user-visible behaviour."
    )

    assert "domain/vetting/throttling_filter.py" not in _identity_sites("company_id"), (
        "throttling_filter is minting a research company_id digest"
    )

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _dotted(node.func).endswith("count_applications_for_company")
    ]
    assert calls, (
        "the per-company cap no longer calls count_applications_for_company — "
        "this pin must be re-pointed at whatever replaced it"
    )
    for call in calls:
        assert call.args, "count_applications_for_company called with no argument"
        arg = call.args[0]
        assert isinstance(arg, ast.Name), (
            "count_applications_for_company is being passed a computed value "
            f"({_dotted(arg)!r}) rather than a plain local holding the raw "
            "company name"
        )


# ── GUARD: the scans are not passing for the wrong reason ────────────────────


@pytest.mark.parametrize(
    "known_site",
    [
        "domain/services/research_identity.py",
    ],
)
def test_the_identity_scan_finds_the_known_sites(known_site: str) -> None:
    """GUARD: the walk still reaches the one known company-hash site.

    A scan that silently stopped parsing ``src`` would satisfy every ratchet
    above by finding nothing. This site is the reason this file exists; if
    the scan cannot see it, the instrument is broken, not the code.
    """
    assert known_site in _identity_sites("company_id"), (
        f"the identity scan no longer finds {known_site}. Either the site "
        "moved — update every map in this file — or the AST walk is broken "
        "and every ratchet here is green for the wrong reason."
    )


@pytest.mark.parametrize(
    "retired_site",
    [
        "domain/services/signal_detectors/base.py",
        "application/workflows/applications_workflow.py",
    ],
)
def test_the_identity_scan_no_longer_sees_the_retired_sites(retired_site: str) -> None:
    """GUARD: the two retired minting sites stay retired.

    These modules held the two incompatible constructions item 4a collapsed.
    They still bind ``company_id`` — as forwarders, not minters — and the
    scan must keep distinguishing the two, because the day one of them
    reappears in this map is the day the join key forked again.
    """
    assert retired_site not in _identity_sites("company_id"), (
        f"{retired_site} is minting a research company_id again. Item 4a "
        "collapsed that construction into domain/services/research_identity.py; "
        "whatever changed there must delegate to compute_company_id, not "
        "re-inline a digest."
    )


def test_the_digest_scan_covers_both_hash_families() -> None:
    """GUARD: the widest scan sees the structural family and the research one.

    ``structural_hashing`` is the math subsystem's; ``research_identity`` is
    research's — it was ``signal_detectors/base`` until item 4a moved the
    company hash out of it. One scan covering both is what makes
    ``test_hash_families_stay_disjoint`` meaningful.
    """
    modules = _digest_modules()
    assert "domain/services/structural_hashing.py" in modules, (
        "the digest scan lost the structural hash family"
    )
    assert "domain/services/research_identity.py" in modules, (
        "the digest scan lost the research hash family"
    )