"""Extracts the semantic Accessibility Object Model (AOM) from the browser.

Reads from the accessibility tree this allows the agent to adapt to
obfuscated class names (Tailwind) and shadow DOMs. Resolver translates
abstract AOM backend node IDs back into interactable ElementInterface
objects using CDP injection, allowing seamless interaction without relying
on CSS selectors.
"""
import logging
from typing import Any

from auto_apply.domain.ports.accessibility_port import (
    IAccessibilityNode,
    IAccessibilityScanner,
)
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface
from auto_apply.domain.types import Locator

logger = logging.getLogger(__name__)


class AOMNode(IAccessibilityNode):
    """Concrete implementation of an accessibility node."""
    __slots__ =['_node_id', '_role', '_name', '_properties']

    def __init__(self, node_id: str, role: str, name: str, properties: dict[str, Any]):
        self._node_id = str(node_id)
        self._role = role.lower()
        self._name = name.lower()  # Lowercase for easier logical matching
        self._properties = properties

    @property
    def node_id(self) -> str: return self._node_id
    @property
    def role(self) -> str: return self._role
    @property
    def name(self) -> str: return self._name
    @property
    def properties(self) -> dict[str, Any]: return self._properties


class AOMScanner(IAccessibilityScanner):
    """Scanner that retrieves the AOM using native browser APIs."""

    def __init__(self, browser: BrowserInterface):
        self.browser = browser

    def get_accessibility_tree(self) -> list[IAccessibilityNode]:
        """Routes the extraction based on the underlying framework."""
        framework = self.browser.framework_name

        logger.debug(f"AOMScanner: Extracting accessibility tree via {framework}")

        if framework == "selenium":
            return self._extract_via_cdp()
        elif framework == "playwright":
            return self._extract_via_playwright()
        else:
            raise NotImplementedError(f"AOM extraction not supported for {framework}")

    def _extract_via_cdp(self) -> list[IAccessibilityNode]:
        """Extracts AOM using Chrome DevTools Protocol (Selenium)."""
        nodes =[]
        try:
            driver = self.browser.get_raw_driver()
            # This CDP command returns the entire parsed accessibility tree instantly
            ax_tree = driver.execute_cdp_cmd("Accessibility.getFullAXTree", {})

            for ax_node in ax_tree.get('nodes',[]):
                # We only care about nodes that have a semantic role
                role = ax_node.get('role', {}).get('value')
                if not role or role == 'generic':
                    continue

                name = ax_node.get('name', {}).get('value', '')
                node_id = ax_node.get('backendDOMNodeId')

                # Extract extra properties (required, disabled, etc.)
                props = {}
                for prop in ax_node.get('properties', []):
                    props[prop.get('name')] = prop.get('value', {}).get('value')

                nodes.append(AOMNode(node_id, role, name, props))

        except Exception as e:
            logger.error(f"Failed to extract AOM via CDP: {e}")

        return nodes

    def _extract_via_playwright(self) -> list[IAccessibilityNode]:
        """Extracts AOM using Playwright's native snapshot."""
        nodes =[]
        try:
            page = self.browser.get_raw_page()
            snapshot = page.accessibility.snapshot()

            def _traverse(node):
                role = node.get('role', '')
                name = node.get('name', '')
                # Playwright doesn't expose backendNodeIds directly in the snapshot easily,  # noqa: E501
                # but we can use CSS selectors or ARIA locators later.
                # For this mathematical model, we generate a hash ID.
                node_id = str(hash(f"{role}{name}"))

                if role and role != 'generic':
                    nodes.append(AOMNode(node_id, role, name, node))

                for child in node.get('children',[]):
                    _traverse(child)

            if snapshot:
                _traverse(snapshot)

        except Exception as e:
            logger.error(f"Failed to extract AOM via Playwright: {e}")

        return nodes

class AOMResolver:
    """Resolves AOM node IDs to actionable browser elements."""

    def __init__(self, browser: BrowserInterface):
        self.browser = browser

    def resolve_node(self, backend_node_id: str) -> ElementInterface | None:
        """Translates a backendNodeId into a live ElementInterface.

        Args:
            backend_node_id (str): The internal ID returned by the AOM/ASP solver.

        Returns:
            Optional[ElementInterface]: The actionable element, or None if stale/missing.
        """  # noqa: E501
        framework = self.browser.framework_name

        if framework == "selenium":
            return self._resolve_via_cdp(backend_node_id)
        elif framework == "playwright":
            return self._resolve_via_playwright(backend_node_id)
        else:
            logger.error(f"AOM resolution not supported for framework: {framework}")
            return None

    def _resolve_via_cdp(self, backend_node_id: str) -> ElementInterface | None:
        """Uses Chrome DevTools Protocol to safely extract the element."""
        try:
            driver = self.browser.get_raw_driver()
            node_id_int = int(backend_node_id)

            # Step 1: Get the live JavaScript Object ID from the Backend Node ID
            # This asks Chrome's memory for the exact object reference.
            resolve_res = driver.execute_cdp_cmd(
                "DOM.resolveNode",
                {"backendNodeId": node_id_int}
            )
            object_id = resolve_res.get("object", {}).get("objectId")

            if not object_id:
                logger.warning(f"Could not resolve AOM node {node_id_int} in memory (Stale?).")  # noqa: E501
                return None

            # Step 2: Inject a temporary tracking attribute
            # We use Runtime.callFunctionOn to execute JS directly on that specific object.  # noqa: E501
            attr_name = "data-aa-target"
            inject_js = f"function() {{ this.setAttribute('{attr_name}', '{backend_node_id}'); }}"  # noqa: E501

            driver.execute_cdp_cmd(
                "Runtime.callFunctionOn",
                {"functionDeclaration": inject_js, "objectId": object_id}
            )

            # Step 3: Grab the element using our standard, framework-agnostic interface
            element = self.browser.find_element(
                Locator.CSS_SELECTOR,
                f"[{attr_name}='{backend_node_id}']"
            )

            # Step 4: Stealth Cleanup (Cover our tracks)
            # Remove the attribute instantly so bot-detectors don't see DOM tampering.
            cleanup_js = f"function() {{ this.removeAttribute('{attr_name}'); }}"
            driver.execute_cdp_cmd(
                "Runtime.callFunctionOn",
                {"functionDeclaration": cleanup_js, "objectId": object_id}
            )

            if element:
                logger.debug(f"Successfully resolved AOM node {backend_node_id} to ElementInterface.")  # noqa: E501
                return element
            else:
                logger.warning(f"Injection succeeded but find_element failed for {backend_node_id}.")  # noqa: E501
                return None

        except Exception as e:
            logger.error(f"CDP Resolution failed for node {backend_node_id}: {e}")
            return None

    def _resolve_via_playwright(self, node_hash: str) -> ElementInterface | None:
        """Resolves using Playwright's native accessibility locators."""
        # Note: Playwright has a built-in `page.get_by_role()` which fundamentally
        # does exactly what our entire pipeline does for Selenium.
        # If the orchestrator detects Playwright, it can bypass the AOM/ASP logic entirely  # noqa: E501
        # and just use `self.browser.get_raw_page().get_by_role("textbox", name="First Name")`.  # noqa: E501
        # We maintain this architecture primarily to empower Selenium (our universal fallback).  # noqa: E501
        logger.warning("Playwright natively supports AOM routing. Use get_by_role instead.")  # noqa: E501
        return None
