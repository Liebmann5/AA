"""The page-health classifier must not run an extraction pass.

``PageClassifier.classify`` used to end with a full
``miner.mine_jobs(source_name="classifier_probe")`` and return
:attr:`PageType.SERP` when it yielded three or more cards. That result could
not reach a decision: the only consumer of ``classify`` is
``GenericSERPStrategy.execute``, whose single branch is the abort set
``{CAPTCHA_BLOCK, LOGIN_REQUIRED, ERROR_404}``, and the probe could only yield
``SERP`` or fall through to ``UNKNOWN``. Neither aborts. So the mine ran, its
answer was discarded, and the harvest loop then mined the same unscrolled page
again — measured at roughly forty seconds per SERP provider per search on a
live Google page.

These pins are labelled by kind:

* **teeth** — fail against the pre-fix tree for the reason stated. The probe's
  absence is asserted behaviourally (a spy miner is never called; the
  constructor no longer accepts one), not by grepping for a name.
* **behaviour-preserving** — every classification the abort set depends on
  still returns exactly what it returned before.
* **degradation** — a classifier over a hostile browser still answers.

The headline is ``test_execute_mines_once_per_harvest_not_once_extra``: it
drives the real ``GenericSERPStrategy.execute`` over a scripted page and pins
the mine count. Pre-fix that count is one higher, and the extra call carries
``source_name="classifier_probe"`` — which is the whole finding, expressed as
an assertion rather than a claim.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ----------------------------------------------------------------------
# Fixtures — a page that is unremarkable: no captcha, no 404, no JSON-LD,
# no password field, no file input. Pre-fix, exactly the page that fell
# through to the mine probe.
# ----------------------------------------------------------------------


def _plain_browser(title: str = "engineer jobs - Google Search"):
    browser = MagicMock()
    browser.title = title
    browser.execute_script.return_value = False   # no JobPosting JSON-LD
    browser.find_elements.return_value = []       # no password / file inputs
    return browser


class _SpyMiner:
    """Records every mine, and with what source_name."""

    def __init__(self, feed=None):
        self.calls: list[str] = []
        self._feed = list(feed) if feed is not None else None

    def mine_jobs(self, source_name: str):
        self.calls.append(source_name)
        if self._feed is None:
            return []
        if self._feed:
            return self._feed.pop(0)
        return []


def _classifier(browser, challenge: bool = False):
    """Build a classifier, tolerating either constructor signature.

    Deliberately signature-tolerant. The behaviour-preserving pins below must
    exercise *behaviour* on both the pre- and post-fix trees; if this helper
    hard-coded the two-argument form they would all fail pre-fix on a
    TypeError, which would look like teeth while discriminating nothing. The
    spy is returned alongside so a caller can assert it was never mined.
    """
    from auto_apply.adapters.secondary.dom.classifier import (  # noqa: PLC0415
        PageClassifier,
    )

    scanner = SimpleNamespace(is_challenge_present=lambda: challenge)
    spy = _SpyMiner()
    try:
        return PageClassifier(browser, scanner), spy
    except TypeError:
        return PageClassifier(browser, scanner, spy), spy


# ----------------------------------------------------------------------
# teeth
# ----------------------------------------------------------------------


def test_classifier_takes_no_miner():
    """teeth: constructing without a miner raised TypeError before the fix."""
    from auto_apply.adapters.secondary.dom.classifier import (  # noqa: PLC0415
        PageClassifier,
    )

    classifier = PageClassifier(
        _plain_browser(), SimpleNamespace(is_challenge_present=lambda: False)
    )
    assert classifier.classify() is not None


def test_classifier_holds_no_miner_attribute():
    """teeth: the discarded dependency is gone, not merely unused."""
    classifier, _ = _classifier(_plain_browser())
    assert not hasattr(classifier, "miner"), (
        "PageClassifier still carries a miner. Dropping the probe but keeping "
        "the collaborator would leave exactly the built-and-never-read shape "
        "this change exists to remove."
    )


def test_unremarkable_page_classifies_without_mining():
    """teeth: the page that used to reach the probe now returns UNKNOWN cheaply."""
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    browser = _plain_browser()
    classifier, spy = _classifier(browser)
    assert classifier.classify() is PageType.UNKNOWN
    assert spy.calls == [], (
        f"classify() mined the page: {spy.calls}. The unremarkable page is "
        f"exactly the one that used to fall through to the discarded probe."
    )

    scripts = [c.args[0] for c in browser.execute_script.call_args_list]
    assert len(scripts) == 1, (
        f"classify() issued {len(scripts)} execute_script calls; only the "
        f"JSON-LD check should remain."
    )


def test_execute_mines_once_per_harvest_not_once_extra():
    """teeth (headline): execute() no longer pays for a discarded extraction.

    The scripted feed yields the same two jobs on every harvest, so the
    dry-scroll guard (limit 2) stops after three mines. Pre-fix the spy records
    four calls, the first of them ``classifier_probe``.
    """
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (  # noqa: PLC0415
        GenericSERPStrategy,
    )

    jobs = [
        SimpleNamespace(url="https://example.test/1", title="Job 1", company="Acme"),
        SimpleNamespace(url="https://example.test/2", title="Job 2", company="Acme"),
    ]
    miner = _SpyMiner(feed=[list(jobs) for _ in range(12)])

    browser = _plain_browser()
    browser.page_source = "<html><body>no structured data here</body></html>"

    scroller = MagicMock()
    scroller.scroll_to_bottom.return_value = True

    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="ProbePin",
        max_results=100,
        dry_scroll_limit=2,
        inter_scroll_delay_s=0.0,
        scroller=scroller,
    )
    strategy.miner = miner
    strategy.interruption_handler = MagicMock()

    results = strategy.execute()

    assert "classifier_probe" not in miner.calls, (
        f"execute() still runs the discarded classifier mine: {miner.calls}. "
        f"That pass extracts the unscrolled page, throws the answer away, and "
        f"the harvest loop then mines the same page again."
    )
    assert all(name == "ProbePin" for name in miner.calls), miner.calls
    assert len(miner.calls) == 3, (
        f"expected 3 harvest mines (2 dry scrolls then stop), got "
        f"{len(miner.calls)}: {miner.calls}"
    )
    assert {j.url for j in results} == {j.url for j in jobs}


# ----------------------------------------------------------------------
# behaviour-preserving — the abort set is the only thing execute() branches
# on, so each member must still be produced by the same input as before.
# ----------------------------------------------------------------------


def test_captcha_still_classifies_as_captcha_block():
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    classifier, _ = _classifier(_plain_browser(), challenge=True)
    assert classifier.classify() is PageType.CAPTCHA_BLOCK


@pytest.mark.parametrize("title", ["404 Not Found", "Page Not Found — Example"])
def test_error_404_still_classifies_as_error_404(title):
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    classifier, _ = _classifier(_plain_browser(title))
    assert classifier.classify() is PageType.ERROR_404


def test_login_wall_still_classifies_as_login_required():
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    classifier, _ = _classifier(_plain_browser("Sign in to continue"))
    assert classifier.classify() is PageType.LOGIN_REQUIRED


def test_json_ld_page_still_classifies_as_serp():
    """SERP remains reachable — via one execute_script, not a mine."""
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    browser = _plain_browser()
    browser.execute_script.return_value = True
    classifier, _ = _classifier(browser)
    assert classifier.classify() is PageType.SERP


def test_execute_still_aborts_on_each_abort_set_member():
    """The health check that justified keeping the classifier still fires."""
    from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (  # noqa: PLC0415
        GenericSERPStrategy,
    )

    miner = _SpyMiner()
    browser = _plain_browser("404 Not Found")
    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="AbortPin",
        max_results=10,
        inter_scroll_delay_s=0.0,
        scroller=MagicMock(),
    )
    strategy.miner = miner
    strategy.interruption_handler = MagicMock()

    assert strategy.execute() == []
    assert miner.calls == [], (
        f"a page that failed the health check was still mined: {miner.calls}"
    )


# ----------------------------------------------------------------------
# degradation
# ----------------------------------------------------------------------


def test_classifier_survives_a_hostile_browser():
    """A browser that raises on every probe must still yield a PageType."""
    from auto_apply.domain.types import PageType  # noqa: PLC0415

    browser = MagicMock()
    type(browser).title = property(lambda self: "")
    browser.execute_script.side_effect = RuntimeError("no such window")
    browser.find_elements.side_effect = RuntimeError("no such window")

    classifier, _ = _classifier(browser)
    assert classifier.classify() is PageType.UNKNOWN
