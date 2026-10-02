"""Item 6 — cleaned copies of the job pages AA reads, kept on this device.

Research rows could not be checked against the pages they describe: the
page was read, a detector ran, and only the row survived. Current practice
for research that keeps web pages (data-donation studies, The Markup's
Citizen Browser, the WACZ signing spec) is: a separate, specific opt-in;
clean the participant's identifiers out at capture; keep copies locally;
link rows to copies by fingerprint; expire copies; delete on withdrawal.

Each pin's docstring says whether it is TEETH (fails without item 6), a
DIFFERENTIAL, or a GUARD.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.secondary.perception.dom_adapter import DOMScanner
from auto_apply.adapters.secondary.perception.math_perception_adapter import (
    MathPerceptionAdapter,
)
from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.adapters.secondary.research.sqlite_consent_repository import (
    SqliteConsentRepository,
)
from auto_apply.adapters.secondary.research.warc_page_store import (
    WarcPageStore,
    read_warc_records,
)
from auto_apply.application.services.page_copier import (
    COPY_CONTEXTS,
    NullPageCopier,
    PageCopier,
    own_details,
)
from auto_apply.application.services.research_consent import (
    InMemoryConsentRepository,
    ResearchConsentManager,
)
from auto_apply.domain.ports.research_consent_port import (
    PageCopiesState,
    ResearchConsentPort,
)
from auto_apply.domain.services import research_consent_text
from auto_apply.application.workflows.vetting_workflow import VettingWorkflow
from auto_apply.domain.constants import (
    CURRENT_CONSENT_VERSION,
    CURRENT_PAGE_COPIES_VERSION,
)
from auto_apply.domain.models.consent import ConsentRecord
from auto_apply.domain.models.job import Job
from auto_apply.adapters.secondary.research.queued_page_store import QueuedPageCopyStore
from auto_apply.domain.models.page_copy import (
    PageCopy,
    commitment,
    content_digest,
    derive_nonce,
)
from auto_apply.domain.ports.page_copy_port import PageCopierPort, PageCopyStorePort
from auto_apply.domain.ports.perception_port import PerceptionPort
from auto_apply.domain.ports.research_port import JobPostingObservation
from auto_apply.domain.services.page_redaction import REDACTED, redact_page
from auto_apply.domain.services.signal_detectors import DetectionContext, run_all_detectors
from auto_apply.infrastructure import composition_root

EMAIL = "nick.example@mail.test"
PHONE = "(916) 555-0142"
STREET = "1200 J Street Apt 4"

PAGE = f"""<html><head>
<meta name="csrf-token" content="tok-123">
<meta name="description" content="Senior Data Analyst">
<script>window.__user = {{"email": "{EMAIL}"}};</script>
<script src="/app.js"></script>
</head><body onload="track()">
<p>Hi Nick Example — welcome back ({EMAIL}, 916.555.0142)</p>
<h1>Senior Data Analyst</h1>
<p>We will pay $90,000 - $110,000. You will report to the director.</p>
<noscript><img src="/pixel?u=nick"></noscript>
<iframe src="/ads">ad text</iframe><iframe src="/lone">
<object data="x.swf"><param name="a" value="b"></object><embed src="y.swf">
<form><input type="hidden" name="session" value="sess-9f2">
<input name="q" value="{STREET}"><option value="secret-opt">Choice</option>
<textarea name="cover">My cover letter text</textarea></form>
</body></html>"""

PROFILE_INFO = SimpleNamespace(
    first_name="Nick",
    middle_name=None,
    last_name="Example",
    email=EMAIL,
    phone_number=PHONE,
    street_address=STREET,
    city="Sacramento",
    state="CA",
    zip_code="95814",
)


def _clock(day: str = "2026-10-02") -> Any:
    return lambda: f"{day}T12:00:00Z"


KEY = b"test-research-key"


def _copier(root: Path, **kwargs: Any) -> PageCopier:
    values, names = own_details(PROFILE_INFO)
    kwargs.setdefault("clock", _clock())
    kwargs.setdefault("nonce", lambda content: derive_nonce(KEY, content))
    return PageCopier(WarcPageStore(root), own_values=values, own_names=names, **kwargs)


def _all_bytes(root: Path) -> bytes:
    """Every byte kept under root, decompressed — what a reader of the
    folder could see."""
    out = b""
    for f in sorted(root.rglob("*")):
        if f.is_file():
            raw = f.read_bytes()
            out += gzip.decompress(raw) if f.name.endswith(".gz") else raw
    return out


# ── Cleaning ─────────────────────────────────────────────────────────────────


def test_cleaning_removes_every_rule_and_keeps_the_text() -> None:
    """TEETH — scripts, frames, embeds, handlers, hidden fields, form values,
    textarea text and token metas are gone; the posting text stays."""
    cleaned, counts = redact_page(PAGE)
    for gone in (
        "<script", "window.__user", "<noscript", "<iframe", "ad text", "<object",
        "<embed", "onload", "track()", 'type="hidden"', "sess-9f2", "secret-opt",
        "My cover letter text", "csrf-token", "tok-123", f'value="{STREET}"',
    ):
        assert gone not in cleaned, gone
    for kept in ("Senior Data Analyst", "$90,000 - $110,000", "report to the director",
                 '<meta name="description"', "Choice", "<textarea name=\"cover\">"):
        assert kept in cleaned, kept
    rules = dict(counts)
    assert rules["script"] == 2
    assert rules["frame"] == 2
    assert rules["embed"] == 2
    assert rules["hidden_input"] == 1
    assert rules["textarea_text"] == 1
    assert rules["token_meta"] == 1
    assert rules["event_handler"] == 1
    assert "own_details" not in rules


def test_cleaning_is_linear_on_hostile_pages() -> None:
    """TEETH — thousands of unclosed frames and scripts before a large page
    clean in well under a second. A lazy ``<iframe.*?</iframe>`` rescans to
    the end of the page from every unclosed tag: this input took minutes."""
    import time

    hostile = ("<iframe src=x>" * 5000) + ("<script>" * 5000) + ("<textarea>" * 5000)
    hostile += "<p>" + "job text " * 120_000 + "</p>"
    started = time.perf_counter()
    cleaned, counts = redact_page(hostile)
    assert time.perf_counter() - started < 5.0
    assert "<iframe" not in cleaned and "<script" not in cleaned
    assert "job text job text" in cleaned
    assert dict(counts)["frame"] == 5000


def test_a_script_quoting_a_script_tag_is_removed_whole() -> None:
    """GUARD — an open tag inside a removed span does not start a new one."""
    cleaned, counts = redact_page('<p>a</p><script>var s="<script>";</script><p>b</p>')
    assert cleaned == "<p>a</p><p>b</p>"
    assert dict(counts) == {"script": 1}


def test_own_details_go_in_any_case_and_any_phone_format() -> None:
    """TEETH — the person's email (any case), phone (any separators), full
    name and street address become [redacted]."""
    values, names = own_details(PROFILE_INFO)
    html = (f"<p>{EMAIL.upper()} | 916-555-0142 | +1 916 555 0142 | nick example "
            f"| {STREET} | Nick | Example Corp</p>")
    cleaned, counts = redact_page(html, values, names)
    assert EMAIL.upper() not in cleaned
    assert "555" not in cleaned
    assert "nick example" not in cleaned
    assert STREET not in cleaned
    assert "Nick" not in cleaned
    assert dict(counts)["own_details"] >= 6
    assert cleaned.count(REDACTED) == dict(counts)["own_details"]


def test_a_name_that_is_a_word_does_not_wipe_the_word() -> None:
    """DIFFERENTIAL — single names match as written, so a person called
    Will does not lose every "will" from every page; their full name still
    goes in any case."""
    info = SimpleNamespace(first_name="Will", last_name="May", email="", phone_number="",
                           street_address="")
    values, names = own_details(info)
    cleaned, _ = redact_page("<p>You will start in may. Will May, WILL MAY.</p>", values, names)
    assert "You will start in may." in cleaned
    assert "Will May" not in cleaned and "WILL MAY" not in cleaned
    # A person with one name on file: that one name is still a single name.
    solo = SimpleNamespace(first_name="Will", last_name="", email="", phone_number="",
                           street_address="")
    cleaned, _ = redact_page("<p>You will start. Will</p>", *own_details(solo))
    assert "You will start." in cleaned and "Will<" not in cleaned


def test_location_is_not_treated_as_the_persons_detail() -> None:
    """GUARD — city, state and ZIP are where jobs are: research data, kept."""
    values, names = own_details(PROFILE_INFO)
    cleaned, _ = redact_page("<p>Sacramento, CA 95814</p>", values, names)
    assert "Sacramento, CA 95814" in cleaned


# ── The copier ───────────────────────────────────────────────────────────────


def test_the_raw_page_never_reaches_disk(tmp_path: Path) -> None:
    """TEETH — nothing the cleaning removes is anywhere under the folder."""
    copy_id = _copier(tmp_path).copy("job_posting", "https://jobs.example/1", lambda: PAGE)
    assert copy_id is not None
    kept = _all_bytes(tmp_path)
    assert b"Senior Data Analyst" in kept
    for secret in (EMAIL, "916.555.0142", "window.__user", "tok-123", "sess-9f2",
                   "My cover letter text", "Nick Example", STREET):
        assert secret.encode() not in kept, secret


def test_search_pages_are_never_copied(tmp_path: Path) -> None:
    """TEETH — a results page contains the search; it is refused before
    the page is even read."""
    read = MagicMock(return_value=PAGE)
    copier = _copier(tmp_path)
    assert copier.copy("serp", "https://www.google.com/search?q=x", read) is None
    read.assert_not_called()
    assert copier.failures == {"context_not_allowed": 1}
    assert COPY_CONTEXTS == frozenset({"job_posting"})
    assert not tmp_path.joinpath("2026-10-02").exists()


def test_permission_is_read_before_every_copy(tmp_path: Path) -> None:
    """TEETH — turning copies off mid-session stops the very next copy, and
    nothing is read once it is off."""
    allowed = {"on": True}
    read = MagicMock(return_value=PAGE)
    copier = _copier(tmp_path, allowed=lambda: allowed["on"])
    assert copier.copy("job_posting", "https://a/1", read) is not None
    allowed["on"] = False
    read.reset_mock()
    assert copier.copy("job_posting", "https://a/2", lambda: PAGE + "x") is None
    read.assert_not_called()
    assert WarcPageStore(tmp_path).count() == 1


def test_a_broken_permission_check_means_no(tmp_path: Path) -> None:
    """GUARD — unknown permission is no permission."""
    def broken() -> bool:
        raise RuntimeError("consent db locked")
    assert _copier(tmp_path, allowed=broken).copy("job_posting", "u", lambda: PAGE) is None
    assert WarcPageStore(tmp_path).count() == 0


def test_the_copier_never_raises(tmp_path: Path) -> None:
    """GUARD — a page read or a save that blows up is counted, not raised."""
    def boom() -> str:
        raise RuntimeError("driver gone")
    copier = _copier(tmp_path)
    assert copier.copy("job_posting", "u", boom) is None
    assert copier.copy("job_posting", "u", lambda: "   ") is None
    store = MagicMock()
    store.save.side_effect = OSError("disk full")
    broken = PageCopier(store, clock=_clock())
    assert broken.copy("job_posting", "u", lambda: PAGE) is None
    assert copier.failures == {"read_failed": 1, "empty_page": 1}
    assert broken.failures == {"save_failed": 1}


def test_null_copier_reads_nothing() -> None:
    """GUARD — copies off: the page is never read."""
    read = MagicMock()
    assert NullPageCopier().copy("job_posting", "u", read) is None
    read.assert_not_called()
    assert isinstance(NullPageCopier(), PageCopierPort)
    assert isinstance(_copier(Path("/nonexistent")), PageCopierPort)


# ── The fingerprint ──────────────────────────────────────────────────────────


def test_the_fingerprint_is_a_commitment_not_a_page_hash(tmp_path: Path) -> None:
    """TEETH — the row fingerprint cannot be recomputed from the public page
    (that would reveal which postings a person read); with the copy's nonce
    it verifies."""
    copy_id = _copier(tmp_path).copy("job_posting", "https://a/1", lambda: PAGE)
    assert copy_id is not None and copy_id.startswith("commit-sha256:")
    (path,) = tmp_path.rglob("*.warc.gz")
    records = {h["WARC-Type"]: (h, b) for h, b in read_warc_records(path)}
    content = records["resource"][1]
    meta = json.loads(records["metadata"][1])
    assert meta["copy_id"] == copy_id
    assert commitment(bytes.fromhex(meta["nonce"]), content) == copy_id
    assert bytes.fromhex(meta["nonce"]) == derive_nonce(KEY, content)
    assert copy_id.split(":", 1)[1] != hashlib.sha256(content).hexdigest()
    assert content_digest(content).split(":", 1)[1] not in copy_id
    # Someone holding the same public page but not this installation's key:
    assert commitment(derive_nonce(b"another-key", content), content) != copy_id
    assert commitment(b"\x00" * 16, content) != copy_id


def test_page_copy_verifies_only_its_own_content() -> None:
    """GUARD — PageCopy.verifies() fails for altered bytes."""
    nonce = b"\x03" * 16
    good = PageCopy(copy_id=commitment(nonce, b"page"), nonce=nonce.hex(), context="job_posting",
                    url="u", captured_at="2026-10-02T12:00:00Z", content=b"page",
                    redactions=())
    assert good.verifies()
    bad = PageCopy(copy_id=good.copy_id, nonce=good.nonce, context="job_posting", url="u",
                   captured_at=good.captured_at, content=b"pag3", redactions=())
    assert not bad.verifies()


def test_one_page_one_fingerprint(tmp_path: Path) -> None:
    """TEETH — the same cleaned page read twice (later day) has one
    fingerprint and is kept once, with no disk lookup needed to know it."""
    first = _copier(tmp_path).copy("job_posting", "https://a/1", lambda: PAGE)
    again = _copier(tmp_path, clock=_clock("2026-10-03")).copy(
        "job_posting", "https://a/1", lambda: PAGE)
    assert first == again
    assert WarcPageStore(tmp_path).count() == 1
    assert (tmp_path / "2026-10-02").is_dir() and not (tmp_path / "2026-10-03").exists()


def test_a_new_key_keeps_both_copies_verifiable(tmp_path: Path) -> None:
    """GUARD — after the research key changes, the same page is kept again
    under its new fingerprint; the older copy stays (until it expires), so
    rows naming either fingerprint still find their copy."""
    older = _copier(tmp_path).copy("job_posting", "u", lambda: PAGE)
    newer = _copier(tmp_path, nonce=lambda c: derive_nonce(b"rotated", c)).copy(
        "job_posting", "u", lambda: PAGE)
    assert older != newer
    kept = {json.loads(read_warc_records(p)[2][1])["copy_id"] for p in tmp_path.rglob("*.warc.gz")}
    assert kept == {older, newer}


def test_file_names_reveal_no_plain_page_hash(tmp_path: Path) -> None:
    """TEETH (item 7) — a copy's file name comes from its keyed fingerprint,
    never from a plain hash of the page: replay manifests publish file
    names, and a plain page hash there would let anyone holding the same
    public page test whether it was read."""
    copy_id = _copier(tmp_path).copy("job_posting", "u", lambda: PAGE)
    (path,) = tmp_path.rglob("*.warc.gz")
    content = read_warc_records(path)[1][1]
    assert path.name == copy_id.split(":", 1)[1][:16] + ".warc.gz"
    assert hashlib.sha256(content).hexdigest()[:16] not in path.name


def test_derived_nonces_are_keyed_and_separated() -> None:
    """GUARD — deterministic per (key, page), different across keys and
    pages, and never the plain HMAC of the page (context label)."""
    import hmac as _hmac

    assert derive_nonce(KEY, b"p") == derive_nonce(KEY, b"p")
    assert derive_nonce(KEY, b"p") != derive_nonce(KEY, b"q")
    assert derive_nonce(KEY, b"p") != derive_nonce(b"k2", b"p")
    assert len(derive_nonce(KEY, b"p")) == 16
    assert derive_nonce(KEY, b"p") != _hmac.new(KEY, b"p", hashlib.sha256).digest()[:16]


# ── The WARC file ────────────────────────────────────────────────────────────


def test_warc_records_say_what_they_are(tmp_path: Path) -> None:
    """GUARD — warcinfo, resource (not response: AA has the rendered page,
    not the server's bytes), metadata concurrent to the resource."""
    _copier(tmp_path).copy("job_posting", "https://jobs.example/1", lambda: PAGE)
    (path,) = tmp_path.rglob("*.warc.gz")
    assert path.parent.name == "2026-10-02"
    records = read_warc_records(path)
    assert [h["WARC-Type"] for h, _ in records] == ["warcinfo", "resource", "metadata"]
    resource, metadata = records[1][0], records[2][0]
    assert resource["WARC-Target-URI"] == "https://jobs.example/1"
    assert resource["WARC-Payload-Digest"] == content_digest(records[1][1])
    assert metadata["WARC-Concurrent-To"] == resource["WARC-Record-ID"]
    meta = json.loads(records[2][1])
    assert meta["context"] == "job_posting"
    assert meta["captured_at"] == "2026-10-02T12:00:00Z"
    assert meta["method"].startswith("rendered DOM")
    assert meta["redactions"]["script"] == 2
    for headers, block in records:
        assert headers["WARC-Block-Digest"] == content_digest(block)
        assert int(headers["Content-Length"]) == len(block)


def test_same_copy_same_bytes(tmp_path: Path) -> None:
    """GUARD — deterministic files: the same copy writes identical bytes."""
    _copier(tmp_path / "a").copy("job_posting", "u", lambda: PAGE)
    _copier(tmp_path / "b").copy("job_posting", "u", lambda: PAGE)
    (a,) = (tmp_path / "a").rglob("*.warc.gz")
    (b,) = (tmp_path / "b").rglob("*.warc.gz")
    assert a.read_bytes() == b.read_bytes()
    assert not list(tmp_path.rglob("*.partial"))


# ── Expiry and deletion ──────────────────────────────────────────────────────


def test_copies_expire_by_capture_day(tmp_path: Path) -> None:
    """TEETH — older than keep_days goes; younger stays; foreign folders
    are left alone."""
    _copier(tmp_path, clock=_clock("2026-06-01")).copy("job_posting", "u1", lambda: PAGE + "1")
    _copier(tmp_path, clock=_clock("2026-09-30")).copy("job_posting", "u2", lambda: PAGE + "2")
    (tmp_path / "notes").mkdir()
    store = WarcPageStore(tmp_path)
    assert isinstance(store, PageCopyStorePort)
    assert store.expire(date(2026, 10, 2), 90) == 1
    assert store.count() == 1
    assert not (tmp_path / "2026-06-01").exists()
    assert (tmp_path / "notes").exists()
    assert store.purge() == 1
    assert store.count() == 0


# ── Consent ──────────────────────────────────────────────────────────────────


def _manager(repo: Any) -> ResearchConsentManager:
    return ResearchConsentManager(repo, salt_available=lambda: True)


def test_page_copies_need_research_consent_first() -> None:
    """TEETH — a second, specific consent: it cannot be granted without
    current research consent, and it is off by default."""
    mgr = _manager(InMemoryConsentRepository())
    with pytest.raises(ValueError):
        mgr.grant_page_copies()
    mgr.grant_consent()
    assert not mgr.should_copy_pages()
    mgr.grant_page_copies()
    assert mgr.should_copy_pages()
    # The dialog became a versioned PageCopiesDialog with the port extension
    # (FORK 3): attribute access replaces tuple unpacking. The content
    # assertions are unchanged; version and labels are pinned below.
    dialog = mgr.page_copies_dialog()
    assert "Keep Copies" in dialog.title and "never kept" in dialog.body


def test_research_regrant_resets_page_copies() -> None:
    """GUARD — a fresh research grant does not carry page copies over."""
    mgr = _manager(InMemoryConsentRepository())
    mgr.grant_consent()
    mgr.grant_page_copies()
    mgr.withdraw_consent(purge_data=False)
    mgr.grant_consent()
    assert not mgr.should_copy_pages()


def test_page_copies_text_change_turns_copies_off() -> None:
    """GUARD — agreement to an older page-copies text is not agreement."""
    repo = InMemoryConsentRepository()
    mgr = _manager(repo)
    mgr.grant_consent()
    mgr.grant_page_copies()
    rec = repo.load_consent()
    repo.save_consent(ConsentRecord(granted=rec.granted, consent_version=rec.consent_version,
                                    granted_at=rec.granted_at, page_copies=True,
                                    page_copies_version="0.9"))
    assert not mgr.should_copy_pages()
    assert CURRENT_PAGE_COPIES_VERSION != "0.9"


def _sqlite_repo(tmp_path: Path) -> SqliteConsentRepository:
    return SqliteConsentRepository(
        consent_db_path=tmp_path / "consent.db",
        research_db_path=tmp_path / "research" / "r.db",
        page_copies_dir=tmp_path / "research" / "page_copies",
    )


def test_turning_copies_off_deletes_them_unless_kept(tmp_path: Path) -> None:
    """TEETH — off deletes by default; keeping them is an explicit choice."""
    root = tmp_path / "research" / "page_copies"
    mgr = _manager(_sqlite_repo(tmp_path))
    mgr.grant_consent()
    mgr.grant_page_copies()
    _copier(root).copy("job_posting", "u", lambda: PAGE)
    assert mgr.withdraw_page_copies(delete=False) == 0
    assert WarcPageStore(root).count() == 1
    assert mgr.is_active()
    mgr.grant_page_copies()
    assert mgr.withdraw_page_copies() == 1
    assert not root.exists()


@pytest.mark.parametrize("purge", [True, False])
def test_withdrawing_from_research_deletes_copies(tmp_path: Path, purge: bool) -> None:
    """TEETH — withdrawal deletes copies whether or not research rows are
    purged (the withdraw text promises it)."""
    root = tmp_path / "research" / "page_copies"
    mgr = _manager(_sqlite_repo(tmp_path))
    mgr.grant_consent()
    mgr.grant_page_copies()
    _copier(root).copy("job_posting", "u", lambda: PAGE)
    mgr.withdraw_consent(purge_data=purge)
    assert not root.exists()
    assert not mgr.should_copy_pages()


def test_an_old_consent_database_gains_the_page_copy_columns(tmp_path: Path) -> None:
    """TEETH — a database from before item 6 opens, keeps its grant, and
    reads page copies as off."""
    db = tmp_path / "consent.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """CREATE TABLE research_consent (
                   id INTEGER PRIMARY KEY CHECK (id = 1),
                   granted INTEGER NOT NULL DEFAULT 0,
                   consent_version TEXT, granted_at TEXT, withdrawn_at TEXT);
               INSERT INTO research_consent VALUES
                   (1, 1, '2.3', '2026-09-01T00:00:00+00:00', NULL);"""
        )
    conn.close()
    repo = SqliteConsentRepository(consent_db_path=db, research_db_path=tmp_path / "r.db")
    rec = repo.load_consent()
    assert rec.granted and rec.consent_version == "2.3"
    assert rec.page_copies is False and rec.page_copies_version is None
    repo.save_consent(ConsentRecord(granted=True, consent_version=CURRENT_CONSENT_VERSION,
                                    page_copies=True,
                                    page_copies_version=CURRENT_PAGE_COPIES_VERSION))
    again = SqliteConsentRepository(consent_db_path=db, research_db_path=tmp_path / "r.db")
    assert again.load_consent().page_copies is True


# ── Linkage into research rows ───────────────────────────────────────────────


def test_detectors_carry_the_copy_without_changing_identity() -> None:
    """TEETH — every signal names the copy; signal ids are unchanged."""
    base = dict(job_title="Analyst", job_description="Great role. " * 20,
                jurisdiction="CA", posting_hash="ph-1", platform="greenhouse")
    without = run_all_detectors(DetectionContext(**base))
    with_copy = run_all_detectors(DetectionContext(**base, page_copy_id="commit-sha256:ab"))
    assert with_copy.signals, "fixture must fire at least one detector"
    assert [s.signal_id for s in with_copy.signals] == [s.signal_id for s in without.signals]
    assert {s.page_copy_id for s in with_copy.signals} == {"commit-sha256:ab"}
    assert {s.page_copy_id for s in without.signals} == {None}


@pytest.fixture
def _salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(signal_aggregator, "resolve_research_salt", lambda: "test-salt")


def _aggregator(db: Path, tmp_path: Path) -> ResearchSignalAggregator:
    return ResearchSignalAggregator(
        db_path=db, consent_version=CURRENT_CONSENT_VERSION, flush_interval_seconds=0.05,
        provenance_key_path=tmp_path / "key.pem",
    )


def test_rows_link_to_the_copy_and_old_databases_migrate(tmp_path: Path, _salt: None) -> None:
    """TEETH — a database from before item 6 gains page_copy_id; a posting
    observed with a copy writes it on its signals and its examination; the
    signed content is unchanged by it."""
    db = tmp_path / "research" / "r.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """CREATE TABLE research_signals (signal_id TEXT PRIMARY KEY,
                   signal_type TEXT NOT NULL, severity TEXT NOT NULL,
                   confidence REAL NOT NULL, evidence_text TEXT, platform TEXT,
                   jurisdiction TEXT, company_id TEXT, job_category TEXT,
                   detected_date TEXT NOT NULL, schema_version INTEGER DEFAULT 2,
                   consent_version TEXT, posting_hash TEXT, content_hash TEXT,
                   provenance_signature TEXT);
               CREATE TABLE detector_examinations (examination_id TEXT PRIMARY KEY,
                   posting_hash TEXT, platform TEXT, jurisdiction TEXT,
                   detectors_run INTEGER NOT NULL, detectors_roster TEXT NOT NULL,
                   detectors_fired INTEGER NOT NULL, signals_fired INTEGER NOT NULL,
                   detectors_raised INTEGER NOT NULL, examined_date TEXT NOT NULL,
                   schema_version INTEGER DEFAULT 2);"""
        )
    conn.close()
    agg = _aggregator(db, tmp_path)
    agg.start()
    agg.observe_job_posting(JobPostingObservation(
        job_title="Analyst", job_description="Great role. " * 20, jurisdiction="CA",
        platform="greenhouse", page_copy_id="commit-sha256:cd"))
    agg.stop()
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    signals = conn.execute("SELECT * FROM research_signals").fetchall()
    exams = conn.execute("SELECT * FROM detector_examinations").fetchall()
    conn.close()
    assert signals and len(exams) == 1
    assert {r["page_copy_id"] for r in signals} == {"commit-sha256:cd"}
    assert exams[0]["page_copy_id"] == "commit-sha256:cd"
    for row in signals:
        if row["content_hash"] is None:
            continue
        signed = json.dumps({
            "signal_type": row["signal_type"], "severity": row["severity"],
            "confidence": row["confidence"], "evidence_text": row["evidence_text"] or "",
            "platform": row["platform"] or "", "jurisdiction": row["jurisdiction"] or "",
            "detected_date": row["detected_date"], "posting_hash": row["posting_hash"] or "",
        }, sort_keys=True).encode("utf-8")
        assert hashlib.sha256(signed).hexdigest() == row["content_hash"]


# ── The vetting hook ─────────────────────────────────────────────────────────


class _Perception:
    def __init__(self, text: str, html: str = PAGE) -> None:
        self.text, self.html = text, html

    def navigate(self, url: str) -> None:
        pass

    def get_page_text(self) -> str:
        return self.text

    def get_page_html(self) -> str:
        return self.html


def _workflow(perception: Any, copier: Any, observer: Any) -> VettingWorkflow:
    return VettingWorkflow(
        profile=MagicMock(), filters=[], job_repo=MagicMock(), task_queue=MagicMock(),
        event_bus=MagicMock(), text_matcher=MagicMock(), perception_port=perception,
        research_observer=observer, page_copier=copier,
    )


def test_vetting_links_the_copy_into_the_observation(tmp_path: Path) -> None:
    """TEETH — a job page read for vetting is copied, and its observation
    carries the copy's fingerprint."""
    observer = MagicMock()
    copier = _copier(tmp_path)
    job = Job(title="Analyst", company="Acme", url="https://jobs.example/1", source="test")
    wf = _workflow(_Perception("Senior Data Analyst ..."), copier, observer)
    fetch = wf._fetch_job_description(job)
    wf._observe_job_posting(job, fetch)
    (obs,) = [c.args[0] for c in observer.observe_job_posting.call_args_list]
    assert obs.page_copy_id is not None and obs.page_copy_id == fetch.page_copy_id
    assert WarcPageStore(tmp_path).count() == 1


def test_no_page_text_means_no_copy(tmp_path: Path) -> None:
    """GUARD — a title fallback is not a page; nothing is copied or linked."""
    copier = MagicMock()
    job = Job(title="Analyst", company="Acme", url="https://jobs.example/1", source="test")
    fetch = _workflow(_Perception(""), copier, MagicMock())._fetch_job_description(job)
    copier.copy.assert_not_called()
    assert fetch.page_copy_id is None and not fetch.from_page


def test_a_broken_copier_does_not_fail_vetting() -> None:
    """GUARD — a copier that breaks its never-raise promise is contained."""
    copier = MagicMock()
    copier.copy.side_effect = RuntimeError("bad copier")
    job = Job(title="Analyst", company="Acme", url="https://jobs.example/1", source="test")
    fetch = _workflow(_Perception("text"), copier, MagicMock())._fetch_job_description(job)
    assert fetch.from_page and fetch.page_copy_id is None


def test_vetting_defaults_to_no_copies() -> None:
    """GUARD — without a copier, nothing is read for copying."""
    perception = MagicMock()
    perception.get_page_text.return_value = "text"
    job = Job(title="Analyst", company="Acme", url="https://jobs.example/1", source="test")
    fetch = _workflow(perception, None, MagicMock())._fetch_job_description(job)
    perception.get_page_html.assert_not_called()
    assert fetch.page_copy_id is None


# ── Perception ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("adapter_cls", [DOMScanner, MathPerceptionAdapter])
def test_perception_adapters_hand_over_the_rendered_page(adapter_cls: Any) -> None:
    """TEETH — the live adapters return the browser's page source; a
    failing browser gives "" rather than raising."""
    browser = MagicMock()
    browser.page_source = "<html>ok</html>"
    assert adapter_cls(browser).get_page_html() == "<html>ok</html>"
    broken = MagicMock()
    type(broken).page_source = property(lambda self: (_ for _ in ()).throw(RuntimeError()))
    assert adapter_cls(broken).get_page_html() == ""


def test_perception_port_default_is_no_page() -> None:
    """GUARD — a perception mode without a page source simply gives none."""
    assert PerceptionPort.get_page_html(MagicMock()) == ""


# ── Composition ──────────────────────────────────────────────────────────────


def _registry(keep: Any = 90) -> Any:
    reg = MagicMock()
    reg.get_effective_config.side_effect = lambda key, default=None: (
        keep if key == "page_copy_keep_days" else default)
    return reg


def _consent(copy_pages: bool) -> Any:
    consent = MagicMock()
    consent.should_copy_pages.return_value = copy_pages
    return consent


def test_composition_builds_a_copier_only_when_research_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — copies need research actually recording AND the page-copy
    consent; the built copier re-reads consent on every copy."""
    monkeypatch.setattr(composition_root, "PAGE_COPIES_DIR", tmp_path)
    monkeypatch.setenv("AA_RESEARCH_SALT", "test-salt")
    profile = SimpleNamespace(personal_info=PROFILE_INFO)
    off = composition_root.build_page_copier(_registry(), _consent(True), profile, False)
    assert isinstance(off, NullPageCopier)
    off2 = composition_root.build_page_copier(_registry(), _consent(False), profile, True)
    assert isinstance(off2, NullPageCopier)
    consent = _consent(True)
    on = composition_root.build_page_copier(_registry(), consent, profile, True)
    assert isinstance(on, PageCopier)
    consent.should_copy_pages.return_value = False
    assert on.copy("job_posting", "u", lambda: PAGE) is None
    # Without the research key there is no keyed nonce: no copies at all.
    monkeypatch.delenv("AA_RESEARCH_SALT")
    keyless = composition_root.build_page_copier(_registry(), _consent(True), profile, True)
    assert isinstance(keyless, NullPageCopier)


def test_composition_copies_are_written_in_the_background(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TEETH — the copier composition builds hands writes to the background
    writer, under a nonce keyed by the research key."""
    monkeypatch.setattr(composition_root, "PAGE_COPIES_DIR", tmp_path)
    monkeypatch.setenv("AA_RESEARCH_SALT", "test-salt")
    on = composition_root.build_page_copier(
        _registry(), _consent(True), SimpleNamespace(personal_info=PROFILE_INFO), True)
    assert isinstance(on, PageCopier)
    assert isinstance(on._store, QueuedPageCopyStore)
    copy_id = on.copy("job_posting", "u", lambda: PAGE)
    assert on._store.close(timeout=5.0)
    (path,) = tmp_path.rglob("*.warc.gz")
    records = read_warc_records(path)
    meta = json.loads(records[2][1])
    assert meta["copy_id"] == copy_id
    assert bytes.fromhex(meta["nonce"]) == derive_nonce(b"test-salt", records[1][1])


@pytest.mark.parametrize("keep", [90, "ninety", 0, True, None])
def test_composition_expires_old_copies_on_every_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, keep: Any
) -> None:
    """TEETH — expiry runs even when copies are off; a nonsense keep_days
    falls back to 90 rather than deleting everything."""
    monkeypatch.setattr(composition_root, "PAGE_COPIES_DIR", tmp_path)
    old = (date.today() - timedelta(days=365)).isoformat()
    _copier(tmp_path, clock=_clock(old)).copy("job_posting", "u1", lambda: PAGE + "old")
    recent = (date.today() - timedelta(days=30)).isoformat()
    _copier(tmp_path, clock=_clock(recent)).copy("job_posting", "u2", lambda: PAGE + "new")
    composition_root.build_page_copier(_registry(keep), _consent(False), None, False)
    assert WarcPageStore(tmp_path).count() == 1


def test_size_settings_fall_back_to_the_yaml_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """GUARD — Absolute Rule 2: no second literal; a bad value falls back to
    runtime_defaults.yaml's own value."""
    from auto_apply.infrastructure.registry import _RUNTIME_DEFAULTS

    for key in ("page_copy_keep_days", "page_copy_max_mb"):
        assert composition_root._positive_int_setting(_bad_registry(), key) == _RUNTIME_DEFAULTS[key]
    good = MagicMock()
    good.get_effective_config.return_value = 7
    assert composition_root._positive_int_setting(good, "page_copy_max_mb") == 7


def _bad_registry() -> Any:
    reg = MagicMock()
    reg.get_effective_config.return_value = "lots"
    return reg


# ── The background writer ────────────────────────────────────────────────────


class _SlowStore:
    """A store whose writes block until released — a slow USB drive."""

    def __init__(self, root: Path) -> None:
        import threading

        self.inner = WarcPageStore(root)
        self.release = threading.Event()
        self.started = threading.Event()

    def save(self, copy: PageCopy) -> str:
        self.started.set()
        assert self.release.wait(10)
        return self.inner.save(copy)

    def discard(self, copy: PageCopy) -> None:
        self.inner.discard(copy)

    def expire(self, today: date, keep_days: int) -> int:
        return self.inner.expire(today, keep_days)

    def purge(self) -> int:
        return self.inner.purge()

    def count(self) -> int:
        return self.inner.count()


def test_a_slow_disk_never_slows_the_copy_call(tmp_path: Path) -> None:
    """TEETH — copy() returns while the write is still blocked: vetting does
    no disk I/O for a copy ("Non-Blocking by Design")."""
    slow = _SlowStore(tmp_path)
    queued = QueuedPageCopyStore(slow, idle_seconds=0.2)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    copy_id = copier.copy("job_posting", "u", lambda: PAGE)
    assert copy_id is not None
    assert slow.started.wait(5)
    assert slow.inner.count() == 0  # still being written
    slow.release.set()
    assert queued.close(timeout=5.0)
    assert slow.inner.count() == 1 and queued.written == 1


def test_a_full_queue_drops_the_copy_and_the_link(tmp_path: Path) -> None:
    """TEETH — when the writer is behind, the copy is dropped and counted,
    and the row gets no page_copy_id rather than one naming nothing."""
    slow = _SlowStore(tmp_path)
    queued = QueuedPageCopyStore(slow, max_pending=1, idle_seconds=0.2)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    assert copier.copy("job_posting", "u1", lambda: PAGE + "1") is not None
    assert slow.started.wait(5)  # the writer holds copy 1; the queue is empty
    assert copier.copy("job_posting", "u2", lambda: PAGE + "2") is not None
    assert copier.copy("job_posting", "u3", lambda: PAGE + "3") is None
    assert queued.failures == {"queue_full": 1}
    assert copier.failures == {"not_kept": 1}
    slow.release.set()
    assert queued.close(timeout=5.0)
    assert slow.inner.count() == 2


def test_the_writer_rereads_permission(tmp_path: Path) -> None:
    """TEETH — a copy queued before copies were turned off is not written;
    one being written when they were turned off is deleted again."""
    allowed = {"on": True}
    slow = _SlowStore(tmp_path)
    queued = QueuedPageCopyStore(slow, allowed=lambda: allowed["on"], idle_seconds=0.2)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    copier.copy("job_posting", "u1", lambda: PAGE + "1")
    assert slow.started.wait(5)  # copy 1 is mid-write
    copier.copy("job_posting", "u2", lambda: PAGE + "2")  # queued behind it
    allowed["on"] = False
    slow.release.set()
    assert queued.close(timeout=5.0)
    assert slow.inner.count() == 0
    assert queued.failures == {"withdrawn_during_write": 1, "not_allowed": 1}
    assert queued.written == 0


def test_a_failed_write_is_counted_not_raised(tmp_path: Path) -> None:
    """GUARD — the writer survives a failing disk and keeps going."""
    inner = MagicMock()
    inner.save.side_effect = [OSError("disk full"), "ok"]
    queued = QueuedPageCopyStore(inner, idle_seconds=0.2)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    copier.copy("job_posting", "u1", lambda: PAGE + "1")
    copier.copy("job_posting", "u2", lambda: PAGE + "2")
    assert queued.close(timeout=5.0)
    assert queued.failures == {"write_failed": 1}
    assert queued.written == 1


def test_the_writer_thread_ends_when_idle(tmp_path: Path) -> None:
    """GUARD — a process that builds many sessions does not collect idle
    writer threads; a later copy starts a new one."""
    import time as _time

    queued = QueuedPageCopyStore(WarcPageStore(tmp_path), idle_seconds=0.05)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    copier.copy("job_posting", "u1", lambda: PAGE + "1")
    deadline = _time.monotonic() + 5
    while queued._thread is not None and _time.monotonic() < deadline:
        _time.sleep(0.02)
    assert queued._thread is None
    copier.copy("job_posting", "u2", lambda: PAGE + "2")
    assert queued.close(timeout=5.0)
    assert WarcPageStore(tmp_path).count() == 2


def test_purge_drops_what_is_still_queued(tmp_path: Path) -> None:
    """GUARD — deleting every copy also cancels the ones not yet written."""
    slow = _SlowStore(tmp_path)
    queued = QueuedPageCopyStore(slow, idle_seconds=0.2)
    copier = PageCopier(queued, clock=_clock(), nonce=lambda c: derive_nonce(KEY, c))
    copier.copy("job_posting", "u1", lambda: PAGE + "1")
    assert slow.started.wait(5)
    copier.copy("job_posting", "u2", lambda: PAGE + "2")
    queued.purge()
    slow.release.set()
    assert queued.close(timeout=5.0)
    assert queued.failures == {"not_allowed": 1}
    # Copy 1 was already being written; with no permission check given here
    # it lands. In composition the writer re-reads consent, and a withdrawal
    # deletes it again (test_the_writer_rereads_permission).
    assert slow.inner.count() == 1


# ── Size budget ──────────────────────────────────────────────────────────────


def test_the_oldest_copies_go_first_past_the_size_budget(tmp_path: Path) -> None:
    """TEETH — a USB drive is not filled: past max_bytes the oldest day goes
    first, and the copy just written is never the one deleted."""
    def keep(day: str, text: str, budget: int | None) -> None:
        PageCopier(WarcPageStore(tmp_path, max_bytes=budget), clock=_clock(day),
                   nonce=lambda c: derive_nonce(KEY, c)).copy(
            "job_posting", text, lambda: f"<p>{text}</p>" + "x" * 2000)
    keep("2026-09-01", "a", None)
    keep("2026-09-02", "b", None)
    one = next(tmp_path.rglob("*.warc.gz")).stat().st_size
    store = WarcPageStore(tmp_path, max_bytes=2 * one + one // 2)
    keep("2026-09-03", "c", 2 * one + one // 2)
    assert sorted(p.parent.name for p in tmp_path.rglob("*.warc.gz")) == [
        "2026-09-02", "2026-09-03"]
    assert not (tmp_path / "2026-09-01").exists()
    keep("2026-09-04", "d", 1)  # a budget smaller than one copy
    assert [p.parent.name for p in tmp_path.rglob("*.warc.gz")] == ["2026-09-04"]
    assert store.count() == 1


# ── The port surface (S3 / FORK 3): versioned dialog, status, satisfaction ────


def test_page_copies_dialog_is_versioned_like_the_research_dialog() -> None:
    """TEETH — pre-change the page-copies dialog was a bare (title, body)
    tuple with no version and no button labels, unlike ResearchConsentDialog.
    Red on the old tree by AttributeError on a tuple."""
    dialog = _manager(InMemoryConsentRepository()).page_copies_dialog()
    assert dialog.version == CURRENT_PAGE_COPIES_VERSION
    assert dialog.title == research_consent_text.PAGE_COPIES_TITLE
    assert dialog.body == research_consent_text.PAGE_COPIES_BODY
    assert dialog.agree_label == research_consent_text.PAGE_COPIES_AGREE_LABEL
    assert dialog.decline_label == research_consent_text.DECLINE_LABEL


def test_status_reports_the_page_copies_state() -> None:
    """TEETH — ResearchConsentStatus said nothing about page copies, so a
    surface could not show or change them without reaching into the manager.
    Red on the old tree by AttributeError (no page_copies field)."""
    repo = InMemoryConsentRepository()
    mgr = _manager(repo)
    assert mgr.status().page_copies is PageCopiesState.OFF
    mgr.grant_consent()
    mgr.grant_page_copies()
    status = mgr.status()
    assert status.page_copies is PageCopiesState.ON
    assert status.page_copies_version == CURRENT_PAGE_COPIES_VERSION
    assert status.current_page_copies_version == CURRENT_PAGE_COPIES_VERSION
    rec = repo.load_consent()
    repo.save_consent(ConsentRecord(
        granted=rec.granted,
        consent_version=rec.consent_version,
        granted_at=rec.granted_at,
        page_copies=True,
        page_copies_version="0.9",
    ))
    assert mgr.status().page_copies is PageCopiesState.NEEDS_RECONSENT


def test_manager_satisfies_the_extended_consent_port() -> None:
    """GUARD — ResearchConsentPort now declares the page-copies surface; the
    manager already carried all three methods, so this passes on both trees
    and freezes the structural satisfaction (no wrapper class)."""
    assert isinstance(_manager(InMemoryConsentRepository()), ResearchConsentPort)
