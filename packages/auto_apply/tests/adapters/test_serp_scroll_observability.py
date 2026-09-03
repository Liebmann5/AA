"""Teeth: the scroll-and-mine loop reports one observability line per scroll.

Stage 2 of Batch 2 instruments ``GenericSERPStrategy._scroll_and_mine`` so
every executed scroll step logs step number, scrollHeight before/after,
viewport bottom, harvest new/total, and the dry count — without changing
any behaviour. On the pre-stage tree the assertion below fails with
``AssertionError: assert False``.
"""

import logging
from unittest.mock import Mock

from auto_apply.adapters.secondary.discovery.strategies.serp_strategy import (
    GenericSERPStrategy,
)
from auto_apply.domain.models.job import Job


def test_scroll_and_mine_logs_each_scroll_step(caplog) -> None:
    fast = Mock()
    fast.mine_jobs.side_effect = [
        [Job(title="T", company="C", url="https://x.example/1", source="Google")],
        [],  # second harvest: nothing new -> dry 1, then scroller ends the feed
    ]
    scroller = Mock()
    scroller.next_page.side_effect = [True, False]

    browser = Mock()
    browser.execute_script.side_effect = (
        lambda script: [1200, 950] if "[" in script else 1200
    )

    strategy = GenericSERPStrategy(
        browser=browser,
        search_prefs=None,
        source_tag="Google",
        max_results=30,
        scroller=scroller,
        fast_extractor=fast,
        dry_scroll_limit=3,
        inter_scroll_delay_s=0.0,
    )

    with caplog.at_level(logging.INFO):
        unique = strategy._scroll_and_mine(scroller)

    assert len(unique) == 1
    scroll_lines = [
        r.getMessage() for r in caplog.records if "scroll 1:" in r.getMessage()
    ]
    assert scroll_lines, "expected one observability line for the executed scroll"
    line = scroll_lines[0]
    assert "height 1200 -> 1200" in line
    assert "viewport bottom 950" in line
    assert "harvest: 1 new (total 1)" in line
    assert "dry 0/3" in line
