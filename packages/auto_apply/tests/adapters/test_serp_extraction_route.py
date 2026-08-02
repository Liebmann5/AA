"""SERP extraction behind a port, with the DOM miner kept as the fallback.

The harvest loop used to call ``SemanticMiner`` directly. It now calls a
``SerpExtractionPort``, and ``GoogleProvider`` supplies a fast route built on
the ``page_understanding_port`` that had been injected into it and read by
nothing.

Pins are labelled by kind, and the labels are earned by execution rather than
asserted — every claim below was checked by running these pins against a tree
that lacks the change, and against deliberately wrong implementations of it.

* **teeth (4)** — fail against the pre-stage tree FOR THE REASON STATED, not
  merely because a module is new: the port is unsatisfied, the strategy cannot
  accept a fast route, the provider does not read its injected port.
* **behaviour-preserving (2)** — pass on BOTH trees. They guard the unwired
  path, which must behave exactly as what shipped.
* **mutation-checked (14)** — these cover surface that did not exist before,
  so failing pre-stage proves nothing on its own. What earns them their place
  is that each was verified against a WRONG version of this stage:
    - removing the commitment from ``FallbackSerpExtractor`` (the naive
      "empty always means fall back") fails exactly
      ``test_committed_fast_route_never_pays_for_the_dry_tail``;
    - relaxing the fast route to accept a card with no URL, and letting an
      empty company through instead of "Unknown", fails exactly the three
      parity pins.

The load-bearing pin is ``test_committed_fast_route_never_pays_for_the_dry_tail``.
Without the commitment, an exhausted feed returns no new jobs for
``dry_scroll_limit`` consecutive harvests and every one of them would trigger a
full miner pass — making a search SLOWER than before this stage existed. That
pin is what makes "never worse than today" checkable rather than promised.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


def _job(n: int, source: str = "Pin"):
    from auto_apply.domain.models.job import Job  # noqa: PLC0415

    return Job(
        title=f"Job {n}", company="Acme", url=f"https://example.test/{n}", source=source
    )


class _SpyMiner:
    """Stands in for SemanticMiner: records every call."""

    def __init__(self, feed=None):
        self.calls: list[str] = []
        self._feed = list(feed) if feed is not None else None

    def mine_jobs(self, source_name: str):
        self.calls.append(source_name)
        if self._feed is None:
            return []
        return self._feed.pop(0) if self._feed else []


class _SpyFast:
    """Stands in for the single-script route."""

    def __init__(self, feed=None, raises=None):
        self.calls: list[str] = []
        self._feed = list(feed) if feed is not None else None
        self._raises = raises

    def mine_jobs(self, source_name: str):
        self.calls.append(source_name)
        if self._raises is not None:
            raise self._raises
        if self._feed is None:
            return []
        return self._feed.pop(0) if self._feed else []


def _plain_browser():
    browser = MagicMock()
    browser.title = "engineer jobs - Google Search"
    browser.current_url = "https://www.google.test/search?q=engineer"
    browser.page_source = "<html><body>nothing structured</body></html>"
    browser.execute_script.return_value = False
    browser.find_elements.return_value = []
    return browser


def _strategy(fast=None, **kw):
    """Build a strategy, tolerating a tree without ``fast_extractor``.

    Signature-tolerant on purpose so the behaviour-preserving pins below run
    on both trees rather than all failing pre-stage on a TypeError, which
    would look like teeth while discriminating nothing.
    """
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (  # noqa: PLC0415
        GenericSERPStrategy,
    )

    args = dict(
        browser=_plain_browser(),
        search_prefs=None,
        source_tag="Pin",
        max_results=100,
        dry_scroll_limit=2,
        inter_scroll_delay_s=0.0,
        scroller=MagicMock(),
    )
    args.update(kw)
    if fast is not None:
        args["fast_extractor"] = fast
    strategy = GenericSERPStrategy(**args)
    strategy.interruption_handler = MagicMock()
    return strategy


# ----------------------------------------------------------------------
# teeth
# ----------------------------------------------------------------------


def test_semantic_miner_satisfies_the_port_with_no_wrapper():
    """teeth: the port is shaped to the object discovery already used."""
    from auto_apply.adapters.secondary.discovery.components.miner import (  # noqa: PLC0415
        SemanticMiner,
    )
    from auto_apply.domain.ports.serp_extraction_port import (  # noqa: PLC0415
        SerpExtractionPort,
    )

    miner = SemanticMiner(
        browser=_plain_browser(),
        title_parser=MagicMock(),
        url_parser=MagicMock(),
        company_parser=MagicMock(),
    )
    assert isinstance(miner, SerpExtractionPort), (
        "SemanticMiner must satisfy SerpExtractionPort as-is. A port that "
        "needs an adapter shim around the incumbent implementation is the "
        "wrong shape."
    )


def test_strategy_accepts_a_fast_route_and_stops_calling_the_miner():
    """teeth (headline): a supplied fast route displaces the miner entirely."""
    fast = _SpyFast(feed=[[_job(1)], [_job(1)], [_job(1)], [_job(1)]])
    strategy = _strategy(fast=fast)

    miner = _SpyMiner()
    strategy.miner._fallback = miner  # type: ignore[attr-defined]

    results = strategy.execute()

    assert miner.calls == [], (
        f"the DOM miner ran despite a working fast route: {miner.calls}"
    )
    assert fast.calls, "the fast route was never called"
    assert {j.url for j in results} == {"https://example.test/1"}


def test_google_provider_reads_its_page_understanding_port():
    """teeth: the injected port that nothing read is now read."""
    from auto_apply.adapters.secondary.discovery.providers.google import (  # noqa: PLC0415
        GoogleProvider,
    )

    port = SimpleNamespace(analyze_serp=lambda ctx: SimpleNamespace(job_cards=()))
    provider = GoogleProvider(browser=_plain_browser(), page_understanding_port=port)

    extractor = provider._fast_extractor()
    assert extractor is not None, (
        "GoogleProvider was given a page_understanding_port and built no fast "
        "extractor from it — the port would remain assigned and never read."
    )
    assert hasattr(extractor, "mine_jobs")


def test_google_provider_without_the_port_stays_on_the_miner():
    """teeth: absence of the port must not invent a route."""
    from auto_apply.adapters.secondary.discovery.providers.google import (  # noqa: PLC0415
        GoogleProvider,
    )

    provider = GoogleProvider(browser=_plain_browser())
    assert provider._fast_extractor() is None


# ----------------------------------------------------------------------
# behaviour-preserving — pass on both trees
# ----------------------------------------------------------------------


def test_unwired_strategy_mines_with_the_semantic_miner_directly():
    from auto_apply.adapters.secondary.discovery.components.miner import (  # noqa: PLC0415
        SemanticMiner,
    )

    strategy = _strategy()
    assert isinstance(strategy.miner, SemanticMiner), (
        "with no fast route supplied, self.miner must BE the SemanticMiner "
        "instance — not a wrapper around it."
    )


def test_unwired_harvest_loop_is_unchanged():
    """The dry-scroll guard, dedup and cap behave exactly as before."""
    strategy = _strategy()
    miner = _SpyMiner(feed=[[_job(1), _job(2)] for _ in range(12)])
    strategy.miner = miner

    results = strategy.execute()

    assert len(miner.calls) == 3, f"expected 3 harvests, got {miner.calls}"
    assert {j.url for j in results} == {
        "https://example.test/1",
        "https://example.test/2",
    }


# ----------------------------------------------------------------------
# fallback semantics — Nick's ruled condition
# ----------------------------------------------------------------------


def _fallback(fast, miner):
    from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (  # noqa: PLC0415
        FallbackSerpExtractor,
    )

    return FallbackSerpExtractor(fast, miner)


def test_fast_route_raising_falls_back_to_the_miner():
    fast = _SpyFast(raises=RuntimeError("boom"))
    miner = _SpyMiner(feed=[[_job(7)]])
    route = _fallback(fast, miner)

    assert [j.url for j in route.mine_jobs("Pin")] == ["https://example.test/7"]
    assert route.route_label == "fallback:error"
    assert miner.calls == ["Pin"]


def test_fast_route_returning_nothing_falls_back_to_the_miner():
    fast = _SpyFast(feed=[[]])
    miner = _SpyMiner(feed=[[_job(8)]])
    route = _fallback(fast, miner)

    assert [j.url for j in route.mine_jobs("Pin")] == ["https://example.test/8"]
    assert route.route_label == "fallback:empty"


def test_fast_route_producing_jobs_never_touches_the_miner():
    fast = _SpyFast(feed=[[_job(9)]])
    miner = _SpyMiner()
    route = _fallback(fast, miner)

    assert [j.url for j in route.mine_jobs("Pin")] == ["https://example.test/9"]
    assert route.route_label == "fast"
    assert miner.calls == []


def test_committed_fast_route_never_pays_for_the_dry_tail():
    """The pin that makes 'never worse than today' checkable.

    A feed that is exhausted returns no new jobs for dry_scroll_limit
    consecutive harvests. Without the commitment, each of those empty harvests
    would trigger a full miner pass — turning the cheap tail into the most
    expensive part of the search.
    """
    fast = _SpyFast(feed=[[_job(1)], [], [], [], []])
    miner = _SpyMiner()
    route = _fallback(fast, miner)

    for _ in range(5):
        route.mine_jobs("Pin")

    assert miner.calls == [], (
        f"the miner ran during the dry tail ({len(miner.calls)} times) after "
        f"the fast route had already proven itself. That is slower than not "
        f"having a fast route at all."
    )
    assert len(fast.calls) == 5


def test_committed_fallback_route_does_not_retry_the_fast_path():
    fast = _SpyFast(feed=[[]])
    miner = _SpyMiner(feed=[[_job(1)], [_job(1)], [_job(1)]])
    route = _fallback(fast, miner)

    for _ in range(3):
        route.mine_jobs("Pin")

    assert len(fast.calls) == 1, f"fast route retried: {fast.calls}"
    assert len(miner.calls) == 3


# ----------------------------------------------------------------------
# parity — both routes must agree on what a job is
# ----------------------------------------------------------------------


def _extractor(cards, observer=None, raises=None):
    from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (  # noqa: PLC0415
        PageUnderstandingExtractor,
    )

    def analyze_serp(_ctx):
        if raises is not None:
            raise raises
        return SimpleNamespace(job_cards=tuple(cards))

    return PageUnderstandingExtractor(
        page_understanding=SimpleNamespace(analyze_serp=analyze_serp),
        browser=_plain_browser(),
        observer=observer,
    )


def _card(title="Engineer", company="Acme", url="https://example.test/1"):
    return SimpleNamespace(title=title, company=company, url=url)


@pytest.mark.parametrize(
    "card",
    [
        _card(title=""),
        _card(url=""),
        _card(title="", url=""),
    ],
)
def test_cards_without_title_and_url_are_dropped_as_the_miner_drops_them(card):
    """SemanticMiner requires `title and url`. So must the fast route."""
    assert _extractor([card]).mine_jobs("Pin") == []


def test_empty_company_becomes_unknown_as_the_miner_does():
    jobs = _extractor([_card(company="")]).mine_jobs("Pin")
    assert [j.company for j in jobs] == ["Unknown"]


def test_source_name_is_stamped_on_every_job():
    jobs = _extractor([_card()]).mine_jobs("Google")
    assert [j.source for j in jobs] == ["Google"]


def test_extraction_attempts_are_audited_both_ways():
    observer = MagicMock()
    _extractor([_card(), _card(url="")], observer=observer).mine_jobs("Pin")

    outcomes = [c.args[1] for c in observer.audit_extraction_attempt.call_args_list]
    assert outcomes == [False, True] or outcomes == [True, False], outcomes


# ----------------------------------------------------------------------
# degradation
# ----------------------------------------------------------------------


def test_analyze_serp_raising_yields_no_jobs_rather_than_an_exception():
    assert _extractor([], raises=RuntimeError("no such window")).mine_jobs("Pin") == []


def test_a_browser_that_will_not_answer_still_yields_a_harvest():
    from auto_apply.adapters.secondary.discovery.components.page_understanding_extractor import (  # noqa: PLC0415
        PageUnderstandingExtractor,
    )

    browser = MagicMock()
    type(browser).current_url = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("dead"))
    )
    type(browser).title = property(
        lambda self: (_ for _ in ()).throw(RuntimeError("dead"))
    )

    seen = {}

    def analyze_serp(ctx):
        seen["url"] = ctx.url
        return SimpleNamespace(job_cards=())

    extractor = PageUnderstandingExtractor(
        page_understanding=SimpleNamespace(analyze_serp=analyze_serp),
        browser=browser,
    )
    assert extractor.mine_jobs("Pin") == []
    assert seen["url"] == ""


def test_an_observer_that_raises_does_not_break_extraction():
    observer = MagicMock()
    observer.audit_extraction_attempt.side_effect = RuntimeError("audit down")
    jobs = _extractor([_card()], observer=observer).mine_jobs("Pin")
    assert len(jobs) == 1


# ----------------------------------------------------------------------
# route legibility — the next live run has one question to answer
# ----------------------------------------------------------------------


def test_null_page_understanding_is_not_reported_as_a_fast_route():
    """teeth: a disabled math subsystem must not look like an empty page.

    ``composition_root`` substitutes ``NullPageUnderstandingAdapter`` when the
    math adapter cannot be built, and that adapter answers every
    ``analyze_serp`` with an empty ``SERPStructure``. Wrapped, it would produce
    a harvest logged as "fallback:empty" — the same label a real Google SERP
    gets when the card detector finds nothing. Those are a wiring failure and a
    detector failure respectively, and telling them apart is the entire point
    of the next live run.
    """
    from auto_apply.adapters.secondary.discovery.providers.google import (  # noqa: PLC0415
        GoogleProvider,
    )
    from auto_apply.domain.ports.page_understanding_port import (  # noqa: PLC0415
        NullPageUnderstandingAdapter,
    )

    provider = GoogleProvider(
        browser=_plain_browser(),
        page_understanding_port=NullPageUnderstandingAdapter(),
    )
    assert provider._fast_extractor() is None, (
        "a Null page-understanding port was wrapped as a fast route. Every "
        "harvest would log 'fallback:empty', which is also what a real page "
        "with an undetectable feed logs."
    )


def test_a_real_port_is_still_reported_as_a_fast_route():
    """behaviour-preserving: the Null check must not reject working ports."""
    from auto_apply.adapters.secondary.discovery.providers.google import (  # noqa: PLC0415
        GoogleProvider,
    )

    port = SimpleNamespace(
        analyze_serp=lambda ctx: SimpleNamespace(job_cards=(_card(),))
    )
    provider = GoogleProvider(browser=_plain_browser(), page_understanding_port=port)
    extractor = provider._fast_extractor()
    assert extractor is not None
    assert len(extractor.mine_jobs("Google")) == 1


def test_the_null_substitution_is_not_silent():
    """teeth: a DEBUG line is invisible in the console capture Nick reads.

    Structural, not textual. The invariant is "the except handler that
    substitutes the Null adapter also warns" — asserted over the AST so it
    survives the message being re-worded or split across string literals,
    which is exactly what defeated the first draft of this pin.
    """
    import ast  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    src = Path(__file__).resolve().parents[2] / "src" / "auto_apply"
    tree = ast.parse(
        (src / "infrastructure" / "composition_root.py").read_text(encoding="utf-8")
    )

    handlers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = ast.dump(ast.Module(body=node.body, type_ignores=[]))
        if "NullPageUnderstandingAdapter" in body:
            handlers.append(node)

    assert handlers, (
        "no except handler substitutes NullPageUnderstandingAdapter — this pin "
        "has drifted from the code it guards."
    )

    for handler in handlers:
        levels = {
            n.func.attr
            for n in ast.walk(ast.Module(body=handler.body, type_ignores=[]))
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "logger"
        }
        assert "warning" in levels or "error" in levels, (
            f"the handler that substitutes the Null page-understanding adapter "
            f"logs at {sorted(levels) or 'nothing'}. The console handler is "
            f"capped at INFO, so discovery would silently lose fast SERP "
            f"extraction for a whole session with no trace of why."
        )
