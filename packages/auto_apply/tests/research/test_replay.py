"""Item 7 — replay and determinism.

A research claim is credible when someone else can re-run it and get the
same answer. A live session cannot be re-run (the web changes); the step
from a kept page to the signals derived from it can. `--replay` re-runs
text extraction and the detectors over a fixed corpus of page copies, with
no browser, network, database, research key or clock, and writes
replay.jsonl + manifest.json.

THE claim, pinned here and checked on all six CI legs (three operating
systems x two Python versions): the committed fixture corpus replays to the
committed expected bytes, exactly. A leg whose bytes differ fails.

To re-make the corpus and the expected output after an intentional change
(a detector, the extractor, the record layout):

    AA_REPLAY_REGENERATE=1 uv run pytest tests/research/test_replay.py

and review the diff of tests/fixtures/replay/expected before committing.

Each pin's docstring says whether it is TEETH (fails without item 7), a
DIFFERENTIAL, or a GUARD.
"""

from __future__ import annotations

import ast
import json
import os
import random
import shutil
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from auto_apply.adapters.primary.cli.replay_report import replay_lines
from auto_apply.adapters.secondary.research import signal_aggregator
from auto_apply.adapters.secondary.research.replay_artifact_dir import ReplayArtifactDir
from auto_apply.adapters.secondary.research.signal_aggregator import (
    ResearchSignalAggregator,
)
from auto_apply.adapters.secondary.research.warc_page_store import (
    WarcPageStore,
    read_warc_records,
)
from auto_apply.adapters.secondary.research.warc_replay_corpus import WarcReplayCorpus
from auto_apply.application.services.page_copier import PageCopier
from auto_apply.application.services.replay_service import ReplayService
from auto_apply.application.workflows.vetting_workflow import VettingWorkflow
from auto_apply.domain.constants import CURRENT_CONSENT_VERSION
from auto_apply.domain.models.job import Job
from auto_apply.domain.models.page_copy import PageCopy, PostingFacts, derive_nonce
from auto_apply.domain.models.replay import ReplayCorpus, ReplayItem
from auto_apply.domain.ports.replay_port import ReplayArtifactSinkPort, ReplayCorpusPort
from auto_apply.domain.ports.research_port import JobPostingObservation
from auto_apply.domain.services.posting_context import (
    posting_detection_context,
    posting_observation,
)
from auto_apply.domain.services.replay import NOT_REPLAYED, replay_corpus
from auto_apply.domain.services.signal_detectors import detector_roster
from auto_apply.domain.services.text_extraction import EXTRACTION_METHOD, visible_text

# ── The fixture: how tests/fixtures/replay/corpus is made ───────────────────
# Copies are made by the real page-copy path (PageCopier + WarcPageStore)
# under a fixed, PUBLIC fixture key and each posting's own capture time, so
# they are ordinary page copies. One deliberately broken file exercises the
# skip path.

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "replay"
SOURCES = FIXTURE / "sources.json"
CORPUS = FIXTURE / "corpus"
EXPECTED = FIXTURE / "expected"

#: Public on purpose: fixture copies prove nothing about any contributor.
FIXTURE_KEY = b"aa-replay-fixture-key (public, not a research key)"

BROKEN_NAME = "broken/not-a-page-copy.warc.gz"
BROKEN_BYTES = b"this file is deliberately not a WARC page copy\n"


def build_corpus(dest: Path) -> list[str]:
    """Write every fixture posting as a page copy under ``dest``; return the
    copy ids in source order."""
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    postings = json.loads(SOURCES.read_text(encoding="utf-8"))["postings"]
    ids: list[str] = []
    store = WarcPageStore(dest)
    for posting in postings:
        captured_at = posting["captured_at"]
        copier = PageCopier(
            store,
            clock=lambda captured_at=captured_at: captured_at,
            nonce=lambda content: derive_nonce(FIXTURE_KEY, content),
        )
        facts = (
            PostingFacts(
                job_title=posting["job_title"],
                location=posting["location"],
                platform=posting["platform"],
            )
            if posting["job_title"] is not None
            else None
        )
        copy_id = copier.copy("job_posting", posting["url"], lambda html=posting["html"]: html, facts)
        assert copy_id is not None, posting["url"]
        ids.append(copy_id)
    broken = dest / BROKEN_NAME
    broken.parent.mkdir(parents=True)
    broken.write_bytes(BROKEN_BYTES)
    return ids


SRC = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
PKG = Path(__file__).resolve().parents[2]
AA_VERSION = "0.1.0-test"
REGENERATE = os.environ.get("AA_REPLAY_REGENERATE") == "1"


def _replay(corpus_dir: Path = CORPUS, aa_version: str = AA_VERSION) -> Any:
    return replay_corpus(WarcReplayCorpus(corpus_dir).read(), aa_version=aa_version)


def _package_version() -> str:
    from importlib import metadata

    try:
        return metadata.version("auto_apply")
    except metadata.PackageNotFoundError:
        return "unknown"


# ── The claim: the fixture corpus replays to the committed bytes ────────────


def test_regenerate_fixture_if_asked(tmp_path: Path) -> None:
    """Not a pin: with AA_REPLAY_REGENERATE=1, re-make the corpus and the
    expected output (see the module docstring). Skipped otherwise."""
    if not REGENERATE:
        pytest.skip("set AA_REPLAY_REGENERATE=1 to re-make the replay fixture")
    build_corpus(CORPUS)
    EXPECTED.mkdir(parents=True, exist_ok=True)
    out = _replay(aa_version=_package_version())
    (EXPECTED / "replay.jsonl").write_bytes(out.records)
    (EXPECTED / "manifest.json").write_bytes(out.manifest)


def test_the_fixture_corpus_replays_to_the_committed_bytes() -> None:
    """TEETH — the reproducibility claim itself. Every CI leg replays the
    same committed corpus and must produce the same committed bytes, so two
    legs that differ by one byte cannot both pass."""
    out = _replay(aa_version=_package_version())
    expected_records = (EXPECTED / "replay.jsonl").read_bytes()
    expected_manifest = (EXPECTED / "manifest.json").read_bytes()
    assert out.records == expected_records, (
        "replay.jsonl differs from tests/fixtures/replay/expected. If a "
        "detector, the extractor or the record layout changed on purpose, "
        "re-make it: AA_REPLAY_REGENERATE=1 uv run pytest "
        "tests/research/test_replay.py — and review the diff."
    )
    assert out.manifest == expected_manifest


def test_the_command_reproduces_the_bytes_under_another_hash_seed(tmp_path: Path) -> None:
    """TEETH — end to end, in a separate process with a different hash seed
    and a different working folder: `python -m auto_apply --replay` writes
    exactly the committed bytes. Set and dict iteration orders change with
    the hash seed; nothing in the artifact may depend on them."""
    out_dir = tmp_path / "out"
    env = dict(os.environ)
    env.update(PYTHONHASHSEED="4242", AA_DATA_DIR=str(tmp_path / "data"))
    # The child must run THIS tree's code, exactly as pytest does.
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(SRC.parent), env.get("PYTHONPATH", "")) if p
    )
    env.pop("AA_RESEARCH_SALT", None)
    proc = subprocess.run(
        [sys.executable, "-m", "auto_apply", "--replay", str(CORPUS), "--replay-out", str(out_dir)],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout.decode(errors="replace")[-2000:]
    assert (out_dir / "replay.jsonl").read_bytes() == (EXPECTED / "replay.jsonl").read_bytes()
    assert (out_dir / "manifest.json").read_bytes() == (EXPECTED / "manifest.json").read_bytes()
    environment = json.loads((out_dir / "environment.json").read_bytes())
    assert environment["python"] and "not part of the result" in environment["note"].lower()
    digest = json.loads((EXPECTED / "manifest.json").read_bytes())["artifact"]["sha256"]
    assert digest in proc.stdout.decode(errors="replace")


def test_the_committed_corpus_is_what_the_sources_make(tmp_path: Path) -> None:
    """GUARD — provenance of the fixture: re-making the corpus from
    sources.json gives the same page copies (compared decompressed — gzip
    bytes can differ between zlib builds, the records cannot)."""
    build_corpus(tmp_path / "corpus")

    def contents(root: Path) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for path in sorted(root.rglob("*.warc.gz")):
            name = path.relative_to(root).as_posix()
            out[name] = path.read_bytes() if name == BROKEN_NAME else read_warc_records(path)
        return out

    assert contents(tmp_path / "corpus") == contents(CORPUS)


def test_expected_files_are_plain_lf_utf8() -> None:
    """GUARD — the committed bytes are LF and UTF-8 (git is told not to touch
    them: tests/fixtures/replay/.gitattributes)."""
    for name in ("replay.jsonl", "manifest.json"):
        data = (EXPECTED / name).read_bytes()
        assert b"\r" not in data and data.endswith(b"\n"), name
        data.decode("utf-8")
    attrs = (CORPUS.parent / ".gitattributes").read_text(encoding="utf-8")
    assert "-text" in attrs


# ── What makes it deterministic ─────────────────────────────────────────────


def test_input_order_does_not_matter() -> None:
    """TEETH — the corpus is sorted before replay: the same copies in any
    order give the same bytes (file systems list folders in different
    orders)."""
    corpus = WarcReplayCorpus(CORPUS).read()
    items = list(corpus.items)
    files = list(corpus.files)
    rng = random.Random(7)
    rng.shuffle(items)
    rng.shuffle(files)
    shuffled = ReplayCorpus(files=tuple(files), items=tuple(items), skipped=corpus.skipped)
    assert replay_corpus(shuffled, aa_version=AA_VERSION).records == _replay().records
    assert replay_corpus(shuffled, aa_version=AA_VERSION).manifest == _replay().manifest


def test_dates_come_from_the_capture_not_the_clock() -> None:
    """TEETH — each posting is replayed as of its capture date: every
    signal's date is its copy's capture date, never the replay's."""
    records = [json.loads(line) for line in _replay().records.splitlines()]
    assert records
    today = date.today().isoformat()
    for record in records:
        for signal in record["signals"]:
            assert signal["detected_date"] == record["captured_on"]
            if record["captured_on"] != today:
                assert signal["detected_date"] != today


def test_signal_ids_are_derived_not_random() -> None:
    """TEETH — without a posting identity, live signal ids are random
    uuid4s; a replay's are derived from (copy, type, index)."""
    first = [json.loads(line) for line in _replay().records.splitlines()]
    second = [json.loads(line) for line in _replay().records.splitlines()]
    ids = [s["signal_id"] for r in first for s in r["signals"]]
    assert ids and ids == [s["signal_id"] for r in second for s in r["signals"]]
    assert all(i.startswith("replay-") for i in ids)
    assert len(set(ids)) == len(ids)


def test_no_research_key_is_needed_or_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """TEETH — a replay runs without AA_RESEARCH_SALT, no detector raises
    for want of it, and no company code appears in the artifact."""
    monkeypatch.delenv("AA_RESEARCH_SALT", raising=False)
    records = [json.loads(line) for line in _replay().records.splitlines()]
    assert all(not r["outcomes"] or all(o["outcome"] != "raised" for o in r["outcomes"]) for r in records)
    for record in records:
        for signal in record["signals"]:
            assert "company_id" not in signal


def test_the_manifest_names_everything_and_no_machine() -> None:
    """GUARD — the manifest identifies the result (format, version,
    extraction, detector roster, corpus files and digest, artifact digest,
    skips, what is not replayed) and carries nothing about the machine."""
    out = _replay()
    manifest = json.loads(out.manifest)
    assert manifest["format"] == "aa-replay/1"
    assert manifest["aa_version"] == AA_VERSION
    assert manifest["extraction"] == EXTRACTION_METHOD
    assert manifest["detectors"] == list(detector_roster())
    assert manifest["artifact"]["sha256"] == out.artifact_sha256
    assert manifest["corpus"]["digest"] == out.corpus_digest
    sources = [f["source"] for f in manifest["corpus"]["files"]]
    assert sources == sorted(sources) and BROKEN_NAME in sources
    assert [s["source"] for s in manifest["skipped"]] == [BROKEN_NAME]
    assert [n["input"] for n in manifest["not_replayed"]] == [k for k, _ in NOT_REPLAYED]
    text = out.manifest.decode("utf-8")
    for machine in (str(CORPUS), str(PKG), sys.version.split()[0], sys.platform, "\\"):
        assert machine not in text, machine


def test_a_new_aa_version_is_a_new_result() -> None:
    """GUARD — the version is part of the identity: a new AA version may
    detect differently, so it must not share a digest with an old one."""
    assert _replay(aa_version="1").manifest_sha256 != _replay(aa_version="2").manifest_sha256
    assert _replay(aa_version="1").records == _replay(aa_version="2").records


def test_a_copy_without_posting_facts_replays_honestly() -> None:
    """GUARD — a copy made before item 7 (no posting facts) replays with no
    title, location or jurisdiction, and says so."""
    records = [json.loads(line) for line in _replay().records.splitlines()]
    legacy = [r for r in records if not r["observation"]["facts_recorded"]]
    assert len(legacy) == 1
    assert legacy[0]["observation"]["jurisdiction"] is None
    assert legacy[0]["observation"]["job_title"] == ""


def test_the_fixture_exercises_the_detectors() -> None:
    """GUARD — a fixture that fires nothing proves nothing: the corpus
    makes several detector families fire, including pay transparency."""
    records = [json.loads(line) for line in _replay().records.splitlines()]
    types = {s["signal_type"] for r in records for s in r["signals"]}
    assert len(records) == 9
    assert len(types) >= 5, types
    assert any(t.startswith("ST-") for t in types), types


# ── Extraction ───────────────────────────────────────────────────────────────


def test_visible_text_keeps_text_and_drops_code() -> None:
    """TEETH — no browser-free extraction existed (the vetting comment that
    claimed a BS4 adapter was stale)."""
    page = (
        "<html><head><title>T</title><style>p{}</style></head><body>"
        "<h1>Data&nbsp;Analyst</h1><!-- note --><p>Pay: $90,000&ndash;$110,000</p>"
        "<ul><li>SQL</li><li>Python</li></ul><table><tr><td>A</td><td>B</td></tr></table>"
        '<script>var a="<p>hidden</p>"</script><noscript>x</noscript>Line<br>two</body></html>'
    )
    text = visible_text(page)
    assert text == "Data Analyst\n\nPay: $90,000–$110,000\n\nSQL\n\nPython\n\nA B\n\nLine\ntwo"
    assert "hidden" not in text and "note" not in text
    # Only the body is read, as a live run's body.innerText is.
    assert visible_text("<html>before<body><p>inside</p></body>after</html>") == "inside"


def test_visible_text_is_linear_on_hostile_pages() -> None:
    """GUARD — thousands of unclosed comments, scripts and tags clean fast."""
    import time

    page = "<!--" * 20000 + "<script>" * 10000 + "<p " * 20000 + "x " * 300000
    started = time.perf_counter()
    visible_text(page)
    assert time.perf_counter() - started < 5.0


def test_visible_text_never_raises() -> None:
    """GUARD — any str in, a str out."""
    for page in ("", "<", "<<>>", "&#xFFFFFFFF;", "<body>", "</body><body>x", "\x00\ud800"):
        assert isinstance(visible_text(page), str)


# ── One builder for live and replay ──────────────────────────────────────────


def _calls(path: Path, name: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
        for n in ast.walk(tree)
    )


def test_live_and_replay_share_one_observation_builder() -> None:
    """TEETH — vetting, the aggregator and replay build the detectors' input
    with the same functions, so a replay cannot drift from a live run by one
    side changing alone."""
    vetting = SRC / "application" / "workflows" / "vetting_workflow.py"
    aggregator = SRC / "adapters" / "secondary" / "research" / "signal_aggregator.py"
    replay = SRC / "domain" / "services" / "replay.py"
    assert _calls(vetting, "posting_observation")
    assert not _calls(vetting, "JobPostingObservation")
    assert _calls(aggregator, "posting_detection_context")
    assert _calls(replay, "posting_observation") and _calls(replay, "posting_detection_context")


@pytest.fixture
def _salt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(signal_aggregator, "resolve_research_salt", lambda: "test-salt")


def test_the_aggregator_context_is_the_shared_one(tmp_path: Path, _salt: None) -> None:
    """DIFFERENTIAL — for a posting with no lifecycle history, the live
    aggregator submits exactly the context the shared builder makes."""
    agg = ResearchSignalAggregator(
        db_path=tmp_path / "r.db",
        consent_version=CURRENT_CONSENT_VERSION,
        provenance_key_path=tmp_path / "k.pem",
    )
    seen: list[Any] = []
    agg.submit_context = seen.append  # type: ignore[method-assign]
    observation = posting_observation(
        job_title="Analyst", job_description="text", company_name="Acme",
        location="Sacramento, CA", platform="greenhouse", url="https://x/1",
        seen_on=date.today(), page_copy_id="commit-sha256:aa",
    )
    agg.observe_job_posting(observation)
    assert seen == [posting_detection_context(observation, current_date=date.today())]


def test_vetting_observes_with_the_shared_builder() -> None:
    """DIFFERENTIAL — vetting's observation equals the shared builder's."""
    observer = MagicMock()
    wf = VettingWorkflow(
        profile=MagicMock(), filters=[], job_repo=MagicMock(), task_queue=MagicMock(),
        event_bus=MagicMock(), text_matcher=MagicMock(), research_observer=observer,
    )
    job = Job(title="Analyst", company="Acme", url="https://x/1", source="greenhouse",
              location="Sacramento, CA")
    from auto_apply.application.workflows.vetting_workflow import FetchedDescription

    wf._observe_job_posting(job, FetchedDescription(text="text", from_page=True))
    (obs,) = [c.args[0] for c in observer.observe_job_posting.call_args_list]
    assert isinstance(obs, JobPostingObservation)
    assert obs == posting_observation(
        job_title="Analyst", job_description="text", company_name="Acme",
        location="Sacramento, CA", platform="greenhouse", url="https://x/1",
        seen_on=obs.first_seen_date or date.today(),
    )


# ── Posting facts on page copies ─────────────────────────────────────────────


def test_vetting_keeps_the_posting_facts_with_the_copy(tmp_path: Path) -> None:
    """TEETH — the title, location and platform reach the copy's metadata,
    so a replay can find the jurisdiction the live run used."""

    class _Perception:
        def navigate(self, url: str) -> None:
            pass

        def get_page_text(self) -> str:
            return "Senior Data Analyst"

        def get_page_html(self) -> str:
            return "<body><p>Senior Data Analyst</p></body>"

    copier = PageCopier(
        WarcPageStore(tmp_path), clock=lambda: "2026-10-02T12:00:00Z",
        nonce=lambda c: derive_nonce(FIXTURE_KEY, c),
    )
    wf = VettingWorkflow(
        profile=MagicMock(), filters=[], job_repo=MagicMock(), task_queue=MagicMock(),
        event_bus=MagicMock(), text_matcher=MagicMock(), perception_port=_Perception(),
        research_observer=MagicMock(), page_copier=copier,
    )
    job = Job(title="Senior Data Analyst", company="Acme", url="https://x/1",
              source="greenhouse", location="Sacramento, CA")
    wf._fetch_job_description(job)
    (item,) = WarcReplayCorpus(tmp_path).read().items
    assert item.facts == PostingFacts("Senior Data Analyst", "Sacramento, CA", "greenhouse")


def test_a_copy_without_facts_records_null(tmp_path: Path) -> None:
    """GUARD — no facts given, metadata says null (not an empty guess)."""
    PageCopier(WarcPageStore(tmp_path), clock=lambda: "2026-10-02T12:00:00Z").copy(
        "job_posting", "https://x/1", lambda: "<p>x</p>")
    (path,) = tmp_path.rglob("*.warc.gz")
    meta = json.loads(read_warc_records(path)[2][1])
    assert meta["posting"] is None


# ── Corpus reader and writer ─────────────────────────────────────────────────


def test_the_corpus_reader_skips_and_ignores_correctly(tmp_path: Path) -> None:
    """GUARD — half-written files are not part of a corpus; a non-posting
    copy and an unreadable file are skips with reasons; a missing folder is
    an error."""
    store = WarcPageStore(tmp_path)
    store.save(PageCopy(copy_id="commit-sha256:s", nonce="00", context="search_page",
                        url="https://s", captured_at="2026-10-02T00:00:00Z",
                        content=b"<p>s</p>", redactions=()))
    (tmp_path / "x.warc.partial").write_bytes(b"half")
    (tmp_path / "bad.warc.gz").write_bytes(b"nope")
    corpus = WarcReplayCorpus(tmp_path).read()
    assert [f for f, _ in corpus.files] == sorted(f for f, _ in corpus.files)
    assert all(not f.endswith(".partial") for f, _ in corpus.files)
    assert [s.source for s in corpus.skipped] == ["bad.warc.gz"]
    out = replay_corpus(corpus, aa_version=AA_VERSION)
    assert out.items == 0 and {s.source for s in out.skipped} == {
        "bad.warc.gz", next(f for f, _ in corpus.files if f != "bad.warc.gz")}
    with pytest.raises(FileNotFoundError):
        WarcReplayCorpus(tmp_path / "missing").read()
    assert isinstance(WarcReplayCorpus(tmp_path), ReplayCorpusPort)


def test_the_writer_writes_bytes_exactly(tmp_path: Path) -> None:
    """TEETH — no text mode, no newline translation; plain names only."""
    sink = ReplayArtifactDir(tmp_path / "out")
    assert isinstance(sink, ReplayArtifactSinkPort)
    sink.write({"a.jsonl": b"x\r\ny\n"})
    assert (tmp_path / "out" / "a.jsonl").read_bytes() == b"x\r\ny\n"
    assert not list((tmp_path / "out").glob("*.partial"))
    for bad in ("../x", "a/b", ""):
        with pytest.raises(ValueError):
            sink.write({bad: b""})
    # Text mode would translate "\n" to "\r\n" on Windows only, which a
    # Linux run cannot see; so also hold the writer to bytes by its source.
    source = (SRC / "adapters" / "secondary" / "research" / "replay_artifact_dir.py").read_text(
        encoding="utf-8")
    assert "write_bytes" in source and "write_text" not in source and "open(" not in source


def test_the_service_writes_three_files_and_reports(tmp_path: Path) -> None:
    """GUARD — replay.jsonl and manifest.json are the result; environment.json
    sits beside them, outside every digest; the report counts signals."""
    report = ReplayService(
        WarcReplayCorpus(CORPUS),
        lambda digest: ReplayArtifactDir(tmp_path / digest[:8]),
        aa_version=AA_VERSION,
        environment={"python": "x", "os": "y"},
    ).run()
    out_dir = Path(report.location)
    assert sorted(p.name for p in out_dir.iterdir()) == [
        "environment.json", "manifest.json", "replay.jsonl"]
    assert out_dir.name == report.output.corpus_digest[:8]
    assert sum(n for _, n in report.signals_by_type) == report.output.signals
    lines = replay_lines(report)
    assert report.output.manifest_sha256 in lines[1]
    assert any("Not replayed" in line for line in lines)


def test_replay_has_no_side_channel_into_the_item(tmp_path: Path) -> None:
    """GUARD — an item's record depends on the item alone: replaying it in a
    corpus of one gives the same record as in the full corpus."""
    corpus = WarcReplayCorpus(CORPUS).read()
    first = corpus.items[0]
    alone = replay_corpus(ReplayCorpus(files=(), items=(first,)), aa_version=AA_VERSION)
    full = [line for line in _replay().records.splitlines() if json.loads(line)["copy_id"] == first.copy_id]
    assert alone.records.splitlines() == full


def test_replay_items_are_frozen() -> None:
    """GUARD — inputs cannot be changed under the replay."""
    item = ReplayItem(source="a", copy_id="c", context="job_posting",
                      captured_at="2026-10-02T00:00:00Z", url="u", page="p")
    with pytest.raises(Exception):
        item.page = "q"  # type: ignore[misc]
    assert replace(item, page="q").page == "q"
