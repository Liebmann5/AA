"""Provides a gracefully-degrading CAPTCHA resolution adapter.

On library computers and minimal-bandwidth environments AA targets, paid
third-party CAPTCHA services are unavailable. This adapter attempts basic
heuristics (audio CAPTCHA bypass) and returns False on failure so the
orchestrator can escalate to manual resolution via the event bus.

Payload-shape note (do not simplify):
    The HANDLE_CAPTCHA payload is constructed as a CaptchaResolutionPayload
    (see domain/models/task_payloads.py) but currently ARRIVES HERE AS A DICT,
    because DatabaseManager.get_next_task() rehydrates only Job payloads and
    leaves every other payload as plain JSON. A future change may deliver the
    pydantic model instead. This adapter must therefore read the challenge
    class from EITHER representation.

    The resolution order in _resolve_challenge_type() is deliberate:
        1. the payload's own ``challenge_type`` field (dict key or model attr),
        2. a nested ``context["context"]["type"]`` marker, if one exists,
        3. a legacy top-level ``"type"`` key, for any older caller,
        4. ``"unknown"``.

    It exists because the field's real name is ``challenge_type``. The
    previous one-liner, ``context.get("type")``, read a key that never
    existed on the live path, leaving challenge_type as "unknown" on every
    call and the audio branch below permanently unreachable. Reading
    ``challenge_type`` first is the fix; the fallbacks are deliberate
    tolerances for legacy callers and the nested context dict — they are
    not accidents to be tidied away.
"""

import logging
from typing import TYPE_CHECKING, Any

from auto_apply.domain.ports.resolution_port import ResolutionInterface

if TYPE_CHECKING:
    from auto_apply.domain.ports.browser_port import BrowserInterface

from auto_apply.domain.ports.registry_port import RegistryPort

logger = logging.getLogger(__name__)


class CaptchaResolutionService(ResolutionInterface):
    """Attempts automated CAPTCHA resolution; gracefully degrades to manual.

    Injected by the composition root into AgentOrchestrator. When automatic
    resolution fails (the common case with no paid APIs), returning False
    causes the orchestrator to emit CAPTCHA_REQUIRES_MANUAL_SOLVE so the
    user can intervene.
    """

    def __init__(self, registry: RegistryPort | None = None) -> None:
        self._registry = registry

    @property
    def name(self) -> str:
        return "CaptchaResolutionService"

    def resolve(self, context: Any, driver: "BrowserInterface | None" = None) -> bool:
        """Attempts to resolve a CAPTCHA challenge.

        Args:
            context: Payload from the HANDLE_CAPTCHA WorkUnit. May be either a
                dict (the current live form — DatabaseManager.get_next_task()
                rehydrates only Job payloads) or a CaptchaResolutionPayload
                pydantic model. See the module docstring for the resolution
                order and why it exists.
            driver: Active browser session for DOM interaction. May be None
                when called in a headless or low-resource environment.

        Returns:
            True if the CAPTCHA was solved automatically, False otherwise.
        """
        challenge_type = self._resolve_challenge_type(context)
        logger.info("CAPTCHA challenge received | type=%s", challenge_type)

        if driver is None:
            logger.warning("No browser driver available — cannot attempt auto-resolve")
            return False

        if challenge_type == "audio":
            return self._try_audio_bypass(context, driver)

        logger.info("No automated handler for challenge type=%s", challenge_type)
        return False

    @staticmethod
    def _resolve_challenge_type(context: Any) -> str:
        """Resolves the challenge class from the payload, tolerating both shapes.

        See the module docstring for the resolution order and why it exists.
        Never raises: an unrecognisable payload yields "unknown", which the
        caller treats as "no automated handler available" and escalates.
        """
        # 1. The payload's own field, in either representation.
        if isinstance(context, dict):
            challenge_type = context.get("challenge_type")
        else:
            challenge_type = getattr(context, "challenge_type", None)
        if isinstance(challenge_type, str) and challenge_type.strip():
            return challenge_type.strip()

        # 2. A nested context dict carrying its own type marker.
        if isinstance(context, dict):
            nested = context.get("context")
        else:
            nested = getattr(context, "context", None)
        if isinstance(nested, dict):
            nested_type = nested.get("type")
            if isinstance(nested_type, str) and nested_type.strip():
                return nested_type.strip()

        # 3. Legacy top-level "type" key.
        if isinstance(context, dict):
            legacy = context.get("type")
            if isinstance(legacy, str) and legacy.strip():
                return legacy.strip()

        return "unknown"

    def _try_audio_bypass(
        self, context: dict, driver: "BrowserInterface"
    ) -> bool:
        """Attempts to click the audio CAPTCHA button to switch modes.

        This is a best-effort heuristic. reCAPTCHA's audio challenge still
        requires speech recognition which is not available without paid APIs,
        so this returns False after attempting the mode switch.

        Args:
            context: Challenge metadata.
            driver: Active browser session.

        Returns:
            Always False — audio parsing requires external services.
        """
        from auto_apply.domain.types import Locator  # noqa: PLC0415

        try:
            audio_btn = driver.find_element(
                Locator.CSS_SELECTOR, "#recaptcha-audio-button, .rc-button-audio"
            )
            if audio_btn:
                audio_btn.click()
                logger.info("Switched to audio CAPTCHA mode; manual solve required")
        except Exception as exc:
            logger.debug("Audio bypass attempt failed | error=%s", exc)

        return False
