"""Provides a gracefully-degrading CAPTCHA resolution adapter.

On library computers and minimal-bandwidth environments AA targets, paid
third-party CAPTCHA services are unavailable. This adapter attempts basic
heuristics (audio CAPTCHA bypass) and returns False on failure so the
orchestrator can escalate to manual resolution via the event bus.
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
            context: Payload from the HANDLE_CAPTCHA WorkUnit (dict with
                challenge metadata such as type and iframe src).
            driver: Active browser session for DOM interaction. May be None
                when called in a headless or low-resource environment.

        Returns:
            True if the CAPTCHA was solved automatically, False otherwise.
        """
        challenge_type = context.get("type", "unknown") if isinstance(context, dict) else "unknown"
        logger.info("CAPTCHA challenge received | type=%s", challenge_type)

        if driver is None:
            logger.warning("No browser driver available — cannot attempt auto-resolve")
            return False

        if challenge_type == "audio":
            return self._try_audio_bypass(context, driver)

        logger.info("No automated handler for challenge type=%s", challenge_type)
        return False

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