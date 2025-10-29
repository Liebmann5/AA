# Core Abstractions: Framework-Agnostic Design

The single most important architectural decision in this project is its **framework-agnostic design**. The agent is not hardcoded to use Selenium, Playwright, or any other specific browser automation library. Instead, it operates on a set of abstract "contracts."

This approach is based on the **Dependency Inversion Principle**, a cornerstone of professional software design. It states that high-level modules should not depend on low-level modules; both should depend on abstractions.

## The `BrowserInterface` Contract

The heart of this design is the `BrowserInterface` abstract base class (ABC). This class is a "contract," not a real implementation. It defines *what* a browser should be able to do, but not *how* it does it.

```python
# From: src/auto_apply/core/browser_interface.py

class BrowserInterface(ABC):
    """Abstracts the browser driver itself, defining a contract for control."""

    @abstractmethod
    def get(self, url: str) -> None:
        """Navigates the browser to a specific URL."""
        ...

    @abstractmethod
    def find_element(self, by: By, selector: str) -> Optional[ElementInterface]:
        """Finds a single element on the current page."""
        ...

    @abstractmethod
    def execute_script(self, script: str, *args) -> Any:
        """Executes JavaScript in the current page context."""
        ...

    # ... and many other abstract methods ...
```

The high-level logic, like the `WorkflowOrchestrator` or the scraping strategies, *only* ever interacts with this `BrowserInterface`. It never knows or cares if the underlying engine is Selenium or Playwright.

## The Concrete Adapters

To make the interface useful, we create concrete "adapters" that implement the contract for a specific library.

*   `SeleniumAdapter`: Implements `BrowserInterface` by translating its methods into Selenium `WebDriver` commands.
*   `PlaywrightAdapter`: Implements `BrowserInterface` by translating its methods into Playwright `Page` commands.

This means all the Selenium-specific code is isolated in one file, and all the Playwright-specific code is in another. The rest of the application remains pure and generic.

## The Factory Pattern

So, if the high-level logic doesn't know about Selenium or Playwright, how does it get an actual browser object? It uses a **Factory**.

The `get_driver_adapter` function in `browser_factory.py` is the single entry point. The orchestrator simply asks it for a browser.

```python
# From: src/auto_apply/core/workflow_orchestrator.py

# The orchestrator just says "get me a selenium browser"
browser_adapter = get_driver_adapter(framework="selenium", ...)
```

The factory's job is to handle the messy, low-level details of creating the correct adapter.

```mermaid
graph TD
    A[Orchestrator] -->|1. Asks for a "selenium" browser| B(Browser Factory);
    B -->|2. Instantiates| C(Selenium Factory);
    C -->|3. Creates WebDriver| D[Selenium WebDriver];
    C -->|4. Wraps WebDriver in Adapter| E(Selenium Adapter);
    B -->|5. Returns Adapter| A;

    subgraph "High-Level Logic"
        A
    end

    subgraph "Factory Layer"
        B
    end

    subgraph "Low-Level Implementation"
        C
        D
        E
    end
```

### The Benefits of This Design

*   **Extensibility:** To add support for a new browser library (e.g., `puppeteer`), we only need to create a new adapter (`PuppeteerAdapter`) and a new factory (`PuppeteerFactory`) and add it to the registry. No other code in the application needs to change.
*   **Testability:** Because our high-level logic depends on an interface, we can create a `MockBrowser` adapter for testing. This allows us to run fast, reliable unit tests on components like the scraping strategies without ever needing to open a real browser.
*   **Maintainability:** All the complex, library-specific code is isolated in its own adapter file. If a new version of Selenium breaks something, we only need to fix it in `selenium_adapter.py`.

---

## What's Next?

This abstract design is mirrored in the Evasion Framework, which is one of the most sophisticated parts of the agent.

➡️ **Next: [The Evasion Framework](03_evasion_framework.md)**
```