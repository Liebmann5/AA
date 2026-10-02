"""Item 2 — the item-4b follow-ons: text guard, ATS-host confound, reader.

THE TEXT GUARD. Item 4c ruled that the research record keeps destination
HOSTS and never full URLs, and pinned that no search query reaches any
column (C4). Measured on ecf40cb, the query still reached the record through
three text routes, each with the C4 sentinel:

    discovery_candidates.anchor_text  'Jobs in Sacramento\\nwww.indeed.com
                                       › q-<query>-l-sacramento-jobs'
    discovery_candidates.anchor_text  'https://www.indeed.com/q-<query>-jobs.html'
    discovery_candidates.ad_evidence  '["path segment \\'sponsored-<query>\\'
                                       contains advertising token"]'

The first is Google's own result-link shape (the breadcrumb sits inside the
link); the second is a visible URL used as link text; the third is advertising
evidence quoting a whole path segment.

THE ATS-HOST CONFOUND. A platform that names the employer in the host shows
N employers as N hosts; one that names it in the path shows them as 1. The
classification lives in the ATS descriptors' ``hosts`` lists and is applied
when the data is READ.

THE READER. Nothing read discovery_pages / _cards / _candidates.

Each pin's docstring says whether it is TEETH (fails on ecf40cb), a
DIFFERENTIAL (shows two behaviours side by side) or a GUARD (holds a property
that was already true, so a later change cannot silently break it).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from auto_apply.adapters.primary.cli.research_summary import (
    format_share,
    summary_lines,
)
from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.discovery_reader import (
    read_discovery_rows,
)
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.ports.research_port import (
    DiscoveryCandidateObservation,
    DiscoveryCardObservation,
    DiscoveryObservation,
)
from auto_apply.domain.services import research_consent_text
from auto_apply.domain.services.discovery_taxonomy import (
    UNCLASSIFIED,
    Share,
    summarize_discovery,
)
from auto_apply.domain.services.url_evidence import (
    advertising_evidence,
    evaluate_candidates,
    redact_rendered_urls,
)

#: The C4 sentinel: a token no host, label or code path can produce.
QUERY = "zqsentinel9917"
SEARCH_PAGE = f"https://www.google.com/search?q={QUERY}+jobs"


@pytest.fixture(autouse=True)
def _bypass_research_salt(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same narrow stand-in as test_discovery_observation_persistence.py."""
    monkeypatch.setattr(
        signal_aggregator, "resolve_research_salt", lambda: "test-salt"
    )


# ── helpers ──────────────────────────────────────────────────────────────────


def _observation_from_page(items: list[dict[str, str]], title: str) -> DiscoveryObservation:
    """Run real page items through the real classifier, then build the
    observation exactly as PageUnderstandingExtractor._emit_observation does
    (candidates keep their anchor text; rejections carry advertising
    evidence)."""
    candidates, rejections = evaluate_candidates(
        items, title=title, serp_host="www.google.com", base_url=SEARCH_PAGE
    )
    observed = [
        DiscoveryCandidateObservation(
            original_url=c.original_url,
            resolved_url=c.url,
            resolved_host=c.url.split("/")[2].lower(),
            anchor_text=c.anchor_text,
            source=c.source,
            outcome="candidate",
        )
        for c in candidates
    ]
    observed += [
        DiscoveryCandidateObservation(
            original_url=r.original_url,
            resolved_url=r.resolved_url,
            outcome="rejected",
            rejection_reason=r.reason,
            ad_evidence=r.evidence if "advertising" in r.reason.lower() else (),
        )
        for r in rejections
    ]
    return DiscoveryObservation(
        provider="Google",
        page_host="www.google.com",
        cards=(
            DiscoveryCardObservation(
                card_index=0, title=title, candidates=tuple(observed)
            ),
        ),
    )


def _persist(db_path: Path, *observations: DiscoveryObservation) -> None:
    aggregator = ResearchSignalAggregator(
        db_path=db_path,
        consent_version=CURRENT_CONSENT_VERSION,
        flush_interval_seconds=0.05,
        macro_signal_interval_seconds=3600.0,
        provenance_key_path=db_path.parent / "provenance_key.pem",
    )
    aggregator.start()
    try:
        for observation in observations:
            aggregator.observe_discovery(observation)
    finally:
        aggregator.stop()


def _cells(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        cells: list[str] = []
        for (table,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall():
            for row in conn.execute(f"SELECT * FROM {table}").fetchall():
                cells.extend(str(v) for v in row if v is not None)
        return cells
    finally:
        conn.close()


def _column(db_path: Path, table: str, column: str) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return [r[0] for r in conn.execute(f"SELECT {column} FROM {table}")]
    finally:
        conn.close()


# ── the text guard ───────────────────────────────────────────────────────────


def test_google_breadcrumb_inside_the_link_never_reaches_the_record(
    tmp_path: Path,
) -> None:
    """TEETH — Google wraps the breadcrumb in the result link; on ecf40cb the
    breadcrumb's path (the query) was stored verbatim in anchor_text."""
    db = tmp_path / "research" / "r.db"
    _persist(db, _observation_from_page(
        [{
            "href": f"https://www.indeed.com/q-{QUERY}-l-sacramento-jobs.html",
            "text": f"Jobs in Sacramento\nwww.indeed.com › q-{QUERY}-l-sacramento-jobs",
            "source": "static",
        }],
        title="Data Engineer",
    ))
    cells = _cells(db)
    assert cells, "nothing persisted — this pin would prove nothing"
    assert not [c for c in cells if QUERY in c.lower()]
    assert _column(db, "discovery_candidates", "anchor_text") == [
        "Jobs in Sacramento\nwww.indeed.com"
    ]


def test_visible_url_as_link_text_is_cut_to_its_host(tmp_path: Path) -> None:
    """TEETH — a visible URL used as the link text was stored whole on
    ecf40cb, routing around R1's decision to drop full URLs."""
    db = tmp_path / "research" / "r.db"
    _persist(db, _observation_from_page(
        [{
            "href": f"https://www.indeed.com/q-{QUERY}-jobs.html",
            "text": f"https://www.indeed.com/q-{QUERY}-jobs.html",
            "source": "static",
        }],
        title="Data Engineer",
    ))
    assert not [c for c in _cells(db) if QUERY in c.lower()]
    assert _column(db, "discovery_candidates", "anchor_text") == ["www.indeed.com"]


def test_advertising_evidence_names_the_token_not_the_segment(tmp_path: Path) -> None:
    """TEETH — ecf40cb quoted the whole path segment in ad_evidence, which is
    persisted. The evidence now names the advertising word it matched."""
    url = f"https://www.example.com/sponsored-{QUERY}/x"
    assert advertising_evidence(url) == (
        "path segment contains advertising token ['sponsored']",
    )
    db = tmp_path / "research" / "r.db"
    _persist(db, _observation_from_page(
        [{"href": url, "text": "Ad", "source": "static"}], title="Data Engineer"
    ))
    evidence = _column(db, "discovery_candidates", "ad_evidence")
    assert evidence == ['["path segment contains advertising token [\'sponsored\']"]']
    assert not [c for c in _cells(db) if QUERY in c.lower()]


def test_card_title_rendering_a_url_is_cut_to_its_host(tmp_path: Path) -> None:
    """TEETH — the same guard covers the other persisted text column."""
    db = tmp_path / "research" / "r.db"
    _persist(db, DiscoveryObservation(
        provider="Bing",
        page_host="www.bing.com",
        cards=(DiscoveryCardObservation(
            card_index=0,
            title=f"careers.example.org » jobs » {QUERY}",
            selected_host="careers.example.org",
        ),),
    ))
    assert _column(db, "discovery_cards", "title") == ["careers.example.org"]


@pytest.mark.parametrize(
    "text",
    [
        "Node.js/React Developer",
        "Senior ASP.NET Engineer – Apply",
        "Apply on company site",
        "Software Engineer II (Remote) · via LinkedIn",
        "",
    ],
)
def test_guard_leaves_ordinary_link_text_exactly_as_shown(text: str) -> None:
    """GUARD — the consent text promises link text 'as shown'; only a
    rendered URL may change. Node.js/React looks like host/path and is not
    related to the candidate's host, so it stays."""
    assert redact_rendered_urls(text, {"boards.greenhouse.io"}) == text


def test_bare_host_path_is_cut_only_when_it_is_the_candidates_own_site() -> None:
    """DIFFERENTIAL — the relation to the candidate's own hosts is what tells
    a rendered 'indeed.com/q-…' from a job title."""
    rendered = f"indeed.com/q-{QUERY}-jobs"
    assert redact_rendered_urls(rendered, {"www.indeed.com"}) == "indeed.com"
    assert redact_rendered_urls(rendered, {"boards.greenhouse.io"}) == rendered


# ── the ATS-host confound ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("host", "platform"),
    [
        ("acme.wd5.myworkdayjobs.com", "workday"),
        ("globex.wd1.myworkdayjobs.com", "workday"),
        ("boards.greenhouse.io", "greenhouse"),
        ("job-boards.greenhouse.io", "greenhouse"),
        ("jobs.lever.co", "lever"),
        ("jobs.ashbyhq.com", "ashby"),
        ("careers-acme.icims.com", "icims"),
        ("acme.taleo.net", "taleo"),
        ("BOARDS.GREENHOUSE.IO:443", "greenhouse"),
        ("user@boards.greenhouse.io", "greenhouse"),
        ("notgreenhouse.io", None),
        ("www.linkedin.com", None),
        ("acme.fa.us2.oraclecloud.com", None),
        ("", None),
    ],
)
def test_platform_for_host(host: str, platform: str | None) -> None:
    """TEETH — ecf40cb had no host-level classification at all. A suffix only
    counts on a label boundary (notgreenhouse.io is not greenhouse), and
    oraclecloud.com is deliberately unclaimed (a wrong label is invisible;
    an unclassified host is not)."""
    assert ATSRegistry().platform_for_host(host) == platform


def test_every_shipped_descriptor_declares_hosts_its_own_patterns_use() -> None:
    """GUARD — a descriptor with no hosts would silently drop its platform
    back into raw-host counting; a host its own url_patterns never name is a
    typo. Both fail here."""
    descriptors = ATSRegistry().all_descriptors()
    assert descriptors, "no ATS descriptors loaded — this pin would prove nothing"
    for descriptor in descriptors:
        assert descriptor.hosts, f"{descriptor.name} declares no hosts"
        pattern_hosts = [p.split("/", 1)[0].lower() for p in descriptor.url_patterns]
        for host in descriptor.hosts:
            assert any(
                ph == host or ph.endswith("." + host) for ph in pattern_hosts
            ), f"{descriptor.name}: host {host!r} appears in none of its url_patterns"


def test_platform_grouping_removes_the_confound() -> None:
    """DIFFERENTIAL — three employers on each platform. By raw host,
    Workday shows three destinations and Greenhouse one; by platform, both
    show three."""
    cards = [
        {"selected_host": h}
        for h in (
            "acme.wd5.myworkdayjobs.com",
            "globex.wd1.myworkdayjobs.com",
            "initech.wd3.myworkdayjobs.com",
            "boards.greenhouse.io",
            "boards.greenhouse.io",
            "boards.greenhouse.io",
        )
    ]
    hosts = [c["selected_host"] for c in cards]
    assert len({h for h in hosts if "myworkdayjobs" in h}) == 3
    assert len({h for h in hosts if "greenhouse" in h}) == 1

    summary = summarize_discovery(
        [], cards, [], platform_for_host=ATSRegistry().platform_for_host
    )
    assert dict(summary.destinations_by_platform) == {
        "greenhouse": Share(3, 6),
        "workday": Share(3, 6),
    }
    assert summary.unclassified_hosts == 0


def test_consent_text_discloses_what_the_record_keeps() -> None:
    """GUARD — the text since 2.3 names destination hosts among what may
    name an employer, and says rendered URLs are cut to their host."""
    body = " ".join(research_consent_text.DIALOG_BODY.split())
    assert tuple(int(p) for p in CURRENT_CONSENT_VERSION.split(".")) >= (2, 3)
    assert "Job titles, link texts and destination hosts are stored as shown" in body
    assert "a web address shown inside a link text is cut down to its host" in body


# ── the reader ───────────────────────────────────────────────────────────────


def _funnel() -> tuple[DiscoveryObservation, ...]:
    def cand(host: str, outcome: str, reason: str = "") -> DiscoveryCandidateObservation:
        return DiscoveryCandidateObservation(
            original_url=f"https://{host}/x" if host else "",
            resolved_url=f"https://{host}/x" if host else "",
            resolved_host=host,
            outcome=outcome,
            rejection_reason=reason,
        )

    page_one = DiscoveryObservation(
        provider="Bing", page_host="www.bing.com", architecture="identifier_js",
        sponsored_card_count=1, activation_attempts=2, activation_resolved=1,
        cards=(
            DiscoveryCardObservation(
                card_index=0, title="Data Engineer", resolution_state="resolved",
                selected_host="acme.wd5.myworkdayjobs.com",
                candidates=(cand("acme.wd5.myworkdayjobs.com", "selected"),
                            cand("ads.example.com", "rejected", "advertising evidence")),
            ),
            DiscoveryCardObservation(
                card_index=1, title="Analyst", resolution_state="multi_route",
                candidates=(cand("a.example.com", "candidate"),
                            cand("b.example.com", "candidate")),
            ),
            DiscoveryCardObservation(
                card_index=2, title="Engineer", resolution_state="resolved",
                selected_host="careers.example.org",
                candidates=(cand("careers.example.org", "selected"),),
            ),
        ),
    )
    page_two = DiscoveryObservation(
        provider="Google", page_host="www.google.com", page_state="captcha_block",
        blocked=True, architecture="none",
    )
    return (page_one, page_two)


def test_reader_summarises_what_the_aggregator_wrote(tmp_path: Path) -> None:
    """TEETH — nothing read these tables on ecf40cb. End to end: rows written
    by the real aggregator, read back read-only, summarised with every share
    carrying its denominator."""
    db = tmp_path / "research" / "r.db"
    _persist(db, *_funnel())
    rows = read_discovery_rows(db)
    summary = summarize_discovery(
        rows.pages, rows.cards, rows.candidates,
        platform_for_host=ATSRegistry().platform_for_host, classifier="test",
    )
    assert summary.pages == 2
    assert dict(summary.pages_by_provider) == {"Bing": Share(1, 2), "Google": Share(1, 2)}
    assert summary.blocked_pages == Share(1, 2)
    assert summary.cards == 3
    assert dict(summary.cards_by_resolution) == {
        "resolved": Share(2, 3), "multi_route": Share(1, 3)
    }
    assert summary.sponsored_only_cards == Share(1, 3)
    assert summary.activations_resolved == Share(1, 2)
    assert summary.candidates == 5
    assert dict(summary.candidates_by_outcome) == {
        "candidate": Share(2, 5), "selected": Share(2, 5), "rejected": Share(1, 5)
    }
    assert summary.rejections_by_reason == (("advertising evidence", Share(1, 1)),)
    assert summary.destinations == 2
    assert dict(summary.destinations_by_platform) == {
        "workday": Share(1, 2), UNCLASSIFIED: Share(1, 2)
    }
    assert summary.unclassified_hosts == 1
    lines = summary_lines(summary)
    assert "    workday                            1 of 2 (50.0%)" in lines


def test_reader_never_creates_or_changes_the_database(tmp_path: Path) -> None:
    """GUARD — read-only: a missing database is reported, not created, and an
    existing database file is byte-identical after a read.

    Measured: SQLite opens a WAL-mode database read-only by creating its two
    side files (r.db-wal, empty; r.db-shm, the index) and leaves them. They
    hold no row data and the withdrawal purge deletes them with the
    database, so the guarantee pinned is the one that matters: the database
    file itself is never written."""
    missing = tmp_path / "nowhere" / "r.db"
    with pytest.raises(FileNotFoundError):
        read_discovery_rows(missing)
    assert not missing.parent.exists()

    db = tmp_path / "research" / "r.db"
    _persist(db, *_funnel())
    before = db.read_bytes()
    read_discovery_rows(db)
    assert db.read_bytes() == before
    wal = db.with_name(db.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0


def test_reader_on_a_database_that_predates_the_tables(tmp_path: Path) -> None:
    """GUARD — a database written before item 4c reads as empty, not as an
    error."""
    db = tmp_path / "old.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE research_signals (signal_id TEXT)")
    conn.commit()
    conn.close()
    rows = read_discovery_rows(db)
    assert (rows.pages, rows.cards, rows.candidates) == ((), (), ())


def test_summary_is_deterministic_and_states_empty_denominators() -> None:
    """GUARD — same rows, same summary; a share of nothing has no rate and is
    shown without a percentage rather than as 0%."""
    pages = [{"provider": "B"}, {"provider": "A"}, {"provider": ""}]
    one = summarize_discovery(pages, [], [], platform_for_host=lambda h: None)
    two = summarize_discovery(list(reversed(pages)), [], [], platform_for_host=lambda h: None)
    assert one == two
    assert one.pages_by_provider == (
        ("(none)", Share(1, 3)), ("A", Share(1, 3)), ("B", Share(1, 3))
    )
    assert one.activations_resolved == Share(0, 0)
    assert one.activations_resolved.rate is None
    assert format_share(Share(0, 0)) == "0 of 0"


def test_research_summary_command_prints_and_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """TEETH — the command is the reader's consumer: no such flag on ecf40cb."""
    # Imported here, as test_research_data_home.py does: importing main runs
    # its pre-import argument parse against sys.argv.
    from auto_apply import main as aa_main
    from auto_apply.domain import config

    db = tmp_path / "research" / "r.db"
    _persist(db, *_funnel())
    monkeypatch.setattr(config, "RESEARCH_DB_PATH", db)
    with pytest.raises(SystemExit) as exit_info:
        aa_main._handle_research_summary()
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert "Discovery research summary" in out
    assert "Results pages:  2" in out
    assert "workday" in out

    monkeypatch.setattr(config, "RESEARCH_DB_PATH", tmp_path / "absent" / "r.db")
    with pytest.raises(SystemExit) as exit_info:
        aa_main._handle_research_summary()
    assert exit_info.value.code == 0
    assert "No research data on this device yet" in capsys.readouterr().out
    assert not (tmp_path / "absent").exists()


def test_reader_is_not_the_research_database_path_owner() -> None:
    """GUARD — the reader takes the path it is given; the one-path rule
    (test_research_data_home.py) keeps RESEARCH_DB_PATH the only definition."""
    source = Path(read_discovery_rows.__code__.co_filename).read_text(encoding="utf-8")
    assert "RESEARCH_DB_PATH" not in source
