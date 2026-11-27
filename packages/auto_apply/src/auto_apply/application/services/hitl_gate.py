"""One bounded way to ask the person a question through the approval gate.

**The gate contract.** An approval gate is a callable::

    gate(question, options, *, checkpoint, timeout, kind="choice", private=False) -> str

``timeout`` is how long the gate may wait, in seconds, or None for no limit
(the person turned time limits off: WCAG 2.2 SC 2.2.1). **Returning within
it is the gate's own promise**: the running app's gate,
``SessionController.request_approval``, keeps it with a cancellable wait —
an event the interface thread sets when the person answers, and that
stopping the session sets too — so nothing ever needs to be abandoned. A
pin (``tests/application/test_session_controller_gates.py``) holds the
controller to it.

What :func:`ask_gate` and :func:`ask_text` guarantee on top:

* **no thread is started, and none is abandoned.** The previous version ran
  a gate without a ``timeout`` parameter on a worker thread and walked away
  from it when the time ran out; a gate reading the terminal would then
  still be waiting there and swallow the person's next answer (round-3
  review). A gate that does not take ``timeout`` cannot promise to return,
  so it is not asked: the answer is ``"skip"`` and a warning names the
  wiring fault;
* **asked once**: the gate's signature is inspected, never probed by
  calling it and catching ``TypeError``;
* **fail closed**: no gate, a gate that raised, or an answer that is not
  one of the offered options all mean ``"skip"``;
* **free-text answers only from a gate that says it takes them**
  (``kind="text"``); any non-empty answer other than ``"skip"`` is the
  person's words;
* **private answers stay private**: with ``private=True`` the gate is asked
  not to log or record the answer (the person's answer to a form question);
* **no values in logs** here: only an exception's type is logged.
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Callable, Sequence
from typing import Any

logger = logging.getLogger(__name__)

SKIP = "skip"
CHOICE = "choice"
TEXT = "text"

_warned: set[int] = set()


def gate_keywords(gate: Callable[..., Any]) -> frozenset[str]:
    """The keyword parameters ``gate`` takes (all of them for ``**kwargs``)."""
    try:
        params = list(inspect.signature(gate).parameters.values())
    except (TypeError, ValueError):
        return frozenset()
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params):
        return frozenset({"checkpoint", "timeout", "kind", "private"})
    return frozenset(p.name for p in params if p.kind in (
        inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY))


def accepts_timeout(gate: Callable[..., Any]) -> bool:
    """Does ``gate`` take a ``timeout`` keyword (by name or ``**kwargs``)?"""
    return "timeout" in gate_keywords(gate)


def can_ask_text(gate: Callable[..., Any] | None) -> bool:
    """Can ``gate`` take a typed answer (``kind="text"``) within a time limit?"""
    if gate is None:
        return False
    kw = gate_keywords(gate)
    return "timeout" in kw and "kind" in kw


def _call(gate: Callable[..., Any], question: str, offered: list[str], *, checkpoint: str,
          timeout: float | None, kind: str, private: bool) -> Any:
    kw = gate_keywords(gate)
    if "timeout" not in kw:
        if id(gate) not in _warned:
            _warned.add(id(gate))
            logger.warning(
                "approval gate %s takes no timeout, so it cannot promise to return; "
                "it is not asked (answer: skip). Wire a gate that keeps the contract.",
                getattr(gate, "__qualname__", type(gate).__name__))
        return SKIP
    kwargs: dict[str, Any] = {"checkpoint": checkpoint, "timeout": timeout}
    if kind != CHOICE or "kind" in kw:
        kwargs["kind"] = kind
    if "private" in kw:
        kwargs["private"] = private
    try:
        return gate(question, offered, **kwargs)
    except Exception as exc:
        logger.warning("approval gate raised (%s) at %s", type(exc).__name__, checkpoint)
        return SKIP


def ask_gate(
    gate: Callable[..., Any] | None,
    question: str,
    options: Sequence[str],
    *,
    checkpoint: str,
    timeout: float | None,
    private: bool = False,
) -> str:
    """Ask once, within ``timeout`` seconds (None: no limit); one of
    ``options`` or ``"skip"``."""
    if gate is None:
        return SKIP
    offered = list(options)
    choice = _call(gate, question, offered, checkpoint=checkpoint, timeout=timeout,
                   kind=CHOICE, private=private)
    return choice if isinstance(choice, str) and choice in offered else SKIP


def ask_text(
    gate: Callable[..., Any] | None,
    question: str,
    *,
    checkpoint: str,
    timeout: float | None,
    private: bool = True,
) -> str | None:
    """Ask for a typed answer; the person's words, or None when they skipped,
    did not answer in time, or the gate cannot take typed answers."""
    if not can_ask_text(gate):
        return None
    assert gate is not None
    answer = _call(gate, question, [SKIP], checkpoint=checkpoint, timeout=timeout,
                   kind=TEXT, private=private)
    if not isinstance(answer, str) or not answer.strip() or answer == SKIP:
        return None
    return answer


__all__ = ["CHOICE", "SKIP", "TEXT", "accepts_timeout", "ask_gate", "ask_text",
           "can_ask_text", "gate_keywords"]
