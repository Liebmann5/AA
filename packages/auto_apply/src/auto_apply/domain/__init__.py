"""
The Core Domain.
Exports the foundational interfaces.
"""
from auto_apply.domain.ports.browser_port import BrowserInterface, ElementInterface

# Note: We do NOT import factories or drivers here to prevent circular imports.
# Consumers should import them directly from 'auto_apply.core.drivers'.

__all__ = [
    "BrowserInterface",
    "ElementInterface",
]
