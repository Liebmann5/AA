"""
Defines the abstract base class for all framework-specific factories.
"""
from abc import ABC, abstractmethod
from .proxy_manager import ProxyManager
from ..core.browser_interface import BrowserInterface

class BaseFactory(ABC):
    def __init__(self, proxy_manager: ProxyManager = None):
        self.proxy_manager = proxy_manager

    @abstractmethod
    def get_driver(self, preferred_browser: str) -> BrowserInterface:
        """
        The contract for all factories. Must return an object that conforms
        to the BrowserInterface.
        """
        pass