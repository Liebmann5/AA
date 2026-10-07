"""Item 5 — the labelling tool: studies, storage, sources, analysis, CLI.

Nothing let a person record ground truth before this change: the 20 pages
in detector_samples/ and the paired audit's human arm had no tool, no
format and no analysis. These pins hold the properties a ground-truth set
must have:

* labelling is BLIND — what AA concluded is shown only after the answer is
  saved;
* labels are append-only, byte-stable JSON Lines, and survive a cut line;
* a saved page is opened only as a copy that runs no code and loads nothing;
* every rate is reported with its denominator and interval, and "can't
  tell" is counted, never silently dropped.

Each pin's docstring says TEETH (fails before this change — everything here
is new, so TEETH means the property is load-bearing and was mutation-checked),
DIFFERENTIAL, or GUARD.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from auto_apply.adapters.primary.cli.labeller import CliLabeller
from auto_apply.adapters.secondary.annotation.detector_sample_source import (
    DetectorSampleSource,
    safe_view_html,
    write_detector_sample,
)
from auto_apply.adapters.secondary.annotation.jsonl_store import JsonlAnnotationStore
from auto_apply.application.services.labelling import LabellingService
from auto_apply.domain.models.annotation import Annotation, answers_problems
from auto_apply.domain.ports.annotation_port import (
    AnnotationStorePort,
    ItemSourcePort,
    LabellingPort,
)
from auto_apply.domain.services.annotation_analysis import rate
from auto_apply.domain.services.annotation_studies import (
    BLOCK_PAGES,
    MY_APPLICATIONS,
    STUDIES,
)

CAPTCHA_PAGE = (
    "<html><head><title>Just a moment...</title>"
    "<script>steal()</script><script src='https://evil.example/x.js'></script>"
    "<meta http-equiv='refresh' content='0;url=https://x.example'>"
    "<base href='https://evil.example/'></head>"
    "<body onload='steal()'><h1>Verify you are human</h1>"
    "<iframe src='https://challenges.example/x'></iframe>"
    "<img src='https://tracker.example/p.gif'></body></html>"
)
JOB_PAGE = (
    "<html><body><h1>Data Engineer</h1><form><input name=email></form></body></html>"
)


def _dump(tmp: Path, url: str, html: str) -> None:
    """Save a page with the ONE writer of the detector-sample format, so the
    source reads the real format. The writer lives beside the reader, so the
    two can never drift — the previous producer (a temporary workflow
    diagnostic) was deleted, which is what errored every test in this file."""
    write_detector_sample(tmp / "detector_samples", url, html, "apply-page")


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[LabellingService, Path]]:
    _dump(
        tmp_path,
        "https://boards.example-ats.com/acme/jobs/1",
        CAPTCHA_PAGE,
    )
    _dump(tmp_path, "https://careers.globex.example/jobs/42", JOB_PAGE)
    store = JsonlAnnotationStore(tmp_path / "annotations")
    source = DetectorSampleSource(
        tmp_path / "detector_samples", tmp_path / "annotations" / "_view"
    )
    service = LabellingService(
        STUDIES, store, (source,), clock=lambda: "2026-10-02T00:00:00+00:00"
    )
    yield service, tmp_path


# ── the vocabulary ───────────────────────────────────────────────────────────


def test_answers_are_validated_against_the_study() -> None:
    """TEETH — required questions, choice keys, conditional questions and an
    exclusive "None of these" are all enforced before anything is stored."""
    ok = {"what": "challenge", "passable": "yes"}
    assert answers_problems(BLOCK_PAGES, ok) == []
    assert answers_problems(BLOCK_PAGES, {}) == ["what: required"]
    assert answers_problems(BLOCK_PAGES, {"what": "maybe"})
    assert answers_problems(BLOCK_PAGES, {"what": "page", "passable": "yes"}) == [
        "passable: answered but does not apply"
    ]
    assert answers_problems(BLOCK_PAGES, {"what": "wall"}) == ["passable: required"]
    good = {
        "platform": "workday",
        "gates": ("account",),
        "pay_shown": "none",
        "minutes": 12.0,
        "outcome": "submitted",
    }
    assert answers_problems(MY_APPLICATIONS, good) == []
    assert answers_problems(MY_APPLICATIONS, {**good, "gates": ("none", "captcha")})
    assert answers_problems(MY_APPLICATIONS, {**good, "minutes": -1.0})


def test_every_shipped_study_is_well_formed() -> None:
    """GUARD — unique study ids, unique question ids, unique choice keys, and
    every ask_if names an earlier question and its real keys."""
    assert len({s.id for s in STUDIES}) == len(STUDIES)
    for study in STUDIES:
        seen: set[str] = set()
        for q in study.questions:
            assert q.id not in seen, (study.id, q.id)
            assert len(set(q.choice_keys())) == len(q.choices), (study.id, q.id)
            if q.ask_if is not None:
                source, keys = q.ask_if
                assert source in seen, (study.id, q.id)
                assert set(keys) <= set(study.question(source).choice_keys())
            seen.add(q.id)


# ── storage ──────────────────────────────────────────────────────────────────


def test_store_is_append_only_lf_json_lines_and_survives_a_cut_line(
    tmp_path: Path,
) -> None:
    """TEETH — labels are the ground truth; they are never rewritten, they
    are byte-identical on every platform, and a line cut by a crash is
    skipped and counted instead of losing the file."""
    store = JsonlAnnotationStore(tmp_path)
    first = Annotation("block-pages", 1, "a", "me", (("what", "page"),), "t1")
    second = Annotation("block-pages", 1, "a", "me", (("what", "wall"),), "t2")
    store.append(first)
    store.append(second)
    path = tmp_path / "block-pages.labels.jsonl"
    raw = path.read_bytes()
    assert b"\r" not in raw and raw.count(b"\n") == 2
    assert json.loads(raw.splitlines()[0])["answers"] == {"what": "page"}
    with path.open("ab") as fh:
        fh.write(b'{"study": "block-pages", "vers')  # a crash mid-line
    got = store.annotations("block-pages")
    assert [a.answer("what") for a in got] == ["page", "wall"]
    assert store.unreadable == {"block-pages.labels.jsonl": 1}


def test_store_round_trips_every_answer_kind(tmp_path: Path) -> None:
    """GUARD — choices, several choices, numbers and text come back as the
    same types they went in as."""
    store = JsonlAnnotationStore(tmp_path)
    answers = (
        ("gates", ("account", "captcha")),
        ("minutes", 12.5),
        ("note", "ok"),
        ("platform", "lever"),
    )
    store.append(Annotation("my-applications", 1, "x", "me", answers, "t"))
    assert store.annotations("my-applications")[0].answers == answers


# ── the saved pages ──────────────────────────────────────────────────────────


def test_source_reads_aas_own_dump_format(world: tuple[LabellingService, Path]) -> None:
    """TEETH — the items come from pages saved by ApplicationsWorkflow's real
    dump code; the site is shown, AA's verdicts are kept for the reveal."""
    service, _ = world
    items = DetectorSampleSource(world[1] / "detector_samples", world[1] / "v").items()
    assert {dict(i.display)["site"] for i in items} == {
        "boards.example-ats.com",
        "careers.globex.example",
    }
    for item in items:
        assert dict(item.aa_facts)["quick_scan"] == "BLOCKED"
        assert dict(item.aa_facts)["weighted_check"] == "NOT BLOCKED"


def test_item_id_follows_the_page_not_the_file_name(
    world: tuple[LabellingService, Path],
) -> None:
    """TEETH — a label stays on its page when the file is renamed."""
    _, tmp = world
    source = DetectorSampleSource(tmp / "detector_samples", tmp / "v")
    before = {i.item_id for i in source.items()}
    for path in (tmp / "detector_samples").glob("*.html"):
        path.rename(path.with_name("renamed_" + path.name))
    assert {i.item_id for i in source.items()} == before


def test_a_saved_page_opens_only_as_a_copy_that_runs_and_loads_nothing() -> None:
    """TEETH — the saved HTML is a stranger's page. The copy carries no
    script, frame, event handler, refresh or base tag, and a CSP that
    blocks every network load (measured in headless Chrome: zero requests)."""
    safe = safe_view_html(CAPTCHA_PAGE.encode()).decode().lower()
    for forbidden in (
        "<script",
        "</script",
        "steal()",
        "<iframe",
        "onload=",
        "http-equiv='refresh'",
        "<base",
    ):
        assert forbidden not in safe, forbidden
    assert "content-security-policy" in safe and "default-src 'none'" in safe
    assert "verify you are human" in safe


# ── the service: blind, resumable, honest ───────────────────────────────────


def test_labelling_is_blind(world: tuple[LabellingService, Path]) -> None:
    """TEETH — what a surface shows before the answer carries nothing of
    AA's verdict; the verdict arrives only through reveal()."""
    service, _ = world
    item = service.next_item("block-pages")
    assert item is not None
    shown = " ".join([item.title] + [f"{k} {v}" for k, v in item.display]).upper()
    assert "BLOCKED" not in shown
    assert any(
        "quick scan said: BLOCKED" in line
        for line in service.reveal(item, {"what": "page"})
    )


def test_skip_means_later_and_progress_is_resumable(
    world: tuple[LabellingService, Path],
) -> None:
    """TEETH — a skipped page comes back after the unlabelled ones; a fresh
    service over the same files resumes where the last one stopped."""
    service, tmp = world
    first = service.next_item("block-pages")
    assert first is not None
    service.skip(first)
    second = service.next_item("block-pages")
    assert second is not None and second.item_id != first.item_id
    assert service.record(second, {"what": "page"}, 3.0) == []
    again = LabellingService(
        STUDIES,
        JsonlAnnotationStore(tmp / "annotations"),
        (DetectorSampleSource(tmp / "detector_samples", tmp / "v"),),
    )
    progress = {p.study.id: p for p in again.progress()}["block-pages"]
    assert (progress.done, progress.skipped, progress.total) == (1, 1, 2)
    nxt = again.next_item("block-pages")
    assert nxt is not None and nxt.item_id == first.item_id


def test_invalid_answers_are_refused_and_nothing_is_written(
    world: tuple[LabellingService, Path],
) -> None:
    """GUARD — a bad answer is reported, not stored."""
    service, tmp = world
    item = service.next_item("block-pages")
    assert item is not None
    assert service.record(item, {"what": "nope"}, 1.0)
    assert not (tmp / "annotations" / "block-pages.labels.jsonl").exists()


def test_answers_to_an_older_study_version_are_not_mixed_in(
    world: tuple[LabellingService, Path],
) -> None:
    """GUARD — a version bump means the questions changed; old answers stay
    on disk but do not count toward the current analysis."""
    service, tmp = world
    item = service.next_item("block-pages")
    assert item is not None
    JsonlAnnotationStore(tmp / "annotations").append(
        Annotation("block-pages", 0, item.item_id, "me", (("what", "page"),), "t")
    )
    assert {p.study.id: p for p in service.progress()}["block-pages"].done == 0


# ── what the labels say ──────────────────────────────────────────────────────


def test_block_insights_report_both_checks_with_denominators(
    world: tuple[LabellingService, Path],
) -> None:
    """TEETH — the finding item 5a exists for: which check was right, as a
    count, a denominator and an interval; "can't tell" counted apart."""
    service, _ = world
    first = service.next_item("block-pages")
    assert first is not None
    service.record(first, {"what": "challenge", "passable": "yes"}, 1.0)
    second = service.next_item("block-pages")
    assert second is not None
    service.record(second, {"what": "unsure"}, 1.0)
    text = "\n".join(service.insights("block-pages"))
    assert f"The quick scan was right on {rate(1, 1)}." in text
    assert f"The weighted check was right on {rate(0, 1)}." in text
    assert "Couldn't tell: 1 (left out of both rates)." in text


def test_application_reveal_checks_aas_location_reader(
    world: tuple[LabellingService, Path],
) -> None:
    """TEETH — the audit's typed location is read by AA's own matcher, and a
    posting with no pay inside a pay-transparency law is called out."""
    service, _ = world
    item = service.log_item("my-applications", "https://jobs.example/1", "Engineer")
    answers = {
        "platform": "lever",
        "gates": ("captcha",),
        "pay_shown": "none",
        "location": "Denver, CO",
        "minutes": 10.0,
        "outcome": "submitted",
    }
    assert service.record(item, answers, 5.0) == []
    reveal = "\n".join(service.reveal(item, answers))
    assert "pay-law jurisdiction CO" in reveal
    assert "ST-01" in reveal
    insights = "\n".join(service.insights("my-applications"))
    assert (
        f"No pay shown where a pay-transparency law applies: {rate(1, 1)}." in insights
    )


def test_logging_the_same_posting_twice_revises_one_item(
    world: tuple[LabellingService, Path],
) -> None:
    """GUARD — the audit counts applications, not keystrokes."""
    service, _ = world
    a = service.log_item("my-applications", "https://jobs.example/1", "")
    b = service.log_item("my-applications", " https://jobs.example/1 ", "Engineer")
    assert a.item_id == b.item_id
    assert {p.study.id: p for p in service.progress()}["my-applications"].total == 1


# ── the CLI ──────────────────────────────────────────────────────────────────


def _run(service: LabellingPort, keys: list[str]) -> list[str]:
    out: list[str] = []
    feed = iter(keys)

    def read(prompt: str) -> str:
        out.append(prompt)
        return next(feed)

    CliLabeller(service, read=read, write=out.append, open_page=lambda p: True).run()
    return out


def test_cli_session_saves_as_it_goes_and_reveals_only_after_saving(
    world: tuple[LabellingService, Path],
) -> None:
    """TEETH — the whole loop through the real service and real files: the
    reveal line never appears before the first answer is saved, labels are
    on disk, and the insights screen closes the queue."""
    service, tmp = world
    out = _run(service, ["1", "1", "1", "", "3", "", "q"])
    first_saved = out.index("  ✓ Saved.")
    assert not any("quick scan said" in line for line in out[:first_saved])
    assert any("quick scan said" in line for line in out[first_saved:])
    assert any("Every page is labelled" in line for line in out)
    assert any("The quick scan was right on" in line for line in out)
    lines = (tmp / "annotations" / "block-pages.labels.jsonl").read_bytes().splitlines()
    assert len(lines) == 2


def test_cli_quit_mid_question_keeps_what_was_saved(
    world: tuple[LabellingService, Path],
) -> None:
    """GUARD — q at any prompt stops cleanly; earlier answers are kept and
    the half-answered item is not written."""
    service, tmp = world
    out = _run(service, ["1", "3", "", "q"])
    assert out[-1] == "  Saved. See you next time."
    lines = (tmp / "annotations" / "block-pages.labels.jsonl").read_bytes().splitlines()
    assert len(lines) == 1


def test_cli_logs_an_application(world: tuple[LabellingService, Path]) -> None:
    """GUARD — the audit loop: link, title, the questions, the reveal."""
    service, _ = world
    out = _run(
        service,
        [
            "2",
            "https://jobs.example/9",
            "Analyst",
            "1",
            "1 3",
            "1",
            "Austin, TX",
            "25",
            "1",
            "",
            "n",
            "q",
        ],
    )
    assert any("pay-law jurisdiction none" in line for line in out)
    assert {p.study.id: p for p in service.progress()}["my-applications"].done == 1


def test_the_ports_are_satisfied() -> None:
    """GUARD — structural conformance of the three ports."""
    assert isinstance(JsonlAnnotationStore(Path(".")), AnnotationStorePort)
    assert isinstance(DetectorSampleSource(Path("."), Path(".")), ItemSourcePort)
    assert isinstance(
        LabellingService(STUDIES, JsonlAnnotationStore(Path("."))), LabellingPort
    )
