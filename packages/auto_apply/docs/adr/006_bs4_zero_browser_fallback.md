# ADR‑006: BeautifulSoup Zero‑Browser Fallback

**Status:** Accepted  
**Date:** 2025‑11‑22  
**Deciders:** Nick Liebmann  
**Technical Story:** AutoApply’s worst‑case user is a person on a library computer with 2 GB RAM, no admin rights, and no ability to install or run a modern web browser. The application must still provide value — job discovery, vetting, and page classification — even when every attempt to launch a browser (Selenium, Playwright, or any other tool) fails.

---

## Context

The perception and interaction layers of AA are designed around a live browser session. `MathPerceptionAdapter` and `DOMScanner` both require a running browser to extract DOM trees, classify page states, and fill forms. On machines where no browser can be launched — no Chrome, no Firefox, no Edge, no Safari, and no Playwright binaries — these adapters cannot function. Without a fallback, the entire session would crash at startup.

The “worst‑case first” architectural principle demands that AA degrade gracefully. Job discovery and vetting are still valuable even if forms cannot be submitted. A static HTML fallback gives the user a way to search for jobs, evaluate them against their profile, and save approved listings for later application on a machine that does have a browser.

---

## Decision

We implemented a **static HTML perception path** via `BS4PerceptionAdapter`, which implements the full `PerceptionPort` contract using only Python standard‑library HTTP (`urllib`) and BeautifulSoup for parsing.

The adapter is selected automatically by the composition root when the browser cascade returns no driver. No user action or configuration is required.

### What the adapter does

- **`navigate(url)`** — fetches the URL via an injected `HTTPClientPort` (default: `UrllibHTTPClient`) and stores the decoded HTML and final redirect URL.
- **`scan_page()`** — parses the stored HTML with BeautifulSoup, builds a `UIModel` containing all interactable form elements (`input`, `textarea`, `select`, `button`) and their resolved labels. Label resolution uses a five‑step chain: `aria‑label`, `aria‑labelledby`, `<label for="…">`, ancestor `<label>`, and finally `placeholder`.
- **`get_current_state()`** — classifies the page into one of the 17 `ApplicationState` values using two passes: a keyword scan over visible text (e.g. “thank you for applying” → `SUCCESS`, “sign in to apply” → `LOGIN_WALL`), followed by structural analysis with BS4 (detects modals via `role="dialog"`, redirect‑to‑listing pages via repeated job cards or many apply links, and generic form steps via presence of input elements).

### What the adapter cannot do

- **No JavaScript execution.** Single‑page applications (React, Vue, Angular) that render their content dynamically are essentially opaque — the adapter sees only the initial HTML.
- **No geometry.** Bounding‑box‑dependent logic (convex hull, occlusion, spatial label‑input pairing) is unavailable. All elements are returned with `is_visible=True` as a conservative default.
- **No session cookies beyond the HTTP client’s capabilities.** Sites behind login walls cannot be accessed.
- **No interaction.** The adapter implements `PerceptionPort` only — it cannot click, type, or scroll. The Application Engine still requires an `InteractionPort` for form submission, which is not available in a zero‑browser environment. The engine gracefully degrades: it can classify and plan, but cannot execute.

### Graceful degradation

The adapter degrades at three levels:

1. **BS4 not installed:** If BeautifulSoup is missing, `scan_page()` returns an empty `UIModel` and `get_current_state()` still runs the text‑based keyword scan (using a simple regex fallback to strip HTML tags).
2. **HTTP request fails:** `UrllibHTTPClient` catches all exceptions and returns an `HTTPResponse` with `status_code=0` and empty body. The adapter returns `ApplicationState.UNKNOWN`.
3. **Malformed HTML:** Individual `_build_ui_element()` calls are wrapped in try/except; a single bad tag is skipped without affecting the rest of the page.

---

## Options Considered

### Require a browser; crash otherwise
**Rejected.** Violates the worst‑case‑user constraint. A user without a browser would be completely locked out of AA.

### Use `requests` + regex for page classification only (no form extraction)
**Rejected.** While simpler, this would limit the fallback to page classification only. Extracting form structure from server‑rendered ATS pages (Greenhouse, Lever) is valuable even without interaction — it allows the user to see what fields will be required and pre‑fill their profile accordingly.

### Implement a headless browser download on‑demand
**Rejected.** A library computer does not have the disk space, bandwidth, or permissions to download a 150 MB browser binary. The fallback must work with zero additional downloads.

---

## Consequences

### What becomes easier

- **Universal reach:** AA can run on any machine with Python and an internet connection, regardless of browser availability or admin rights.
- **Testing:** The `BS4PerceptionAdapter` requires only a mock `HTTPClientPort` — no browser, no network. Tests run in milliseconds.
- **Page classification in any tier:** Even users with a live browser can benefit from the static fallback for pre‑screening URLs before dedicating a browser session to them.

### What becomes harder

- **Dynamic page support:** The adapter is inherently limited to server‑rendered HTML. Single‑page applications that load job listings via JavaScript are invisible. Users must understand this limitation.
- **Maintaining dual perception paths:** Both the live‑browser perception adapters (`MathPerceptionAdapter`, `DOMScanner`) and the static adapter must be kept consistent. Adding a new `ApplicationState` requires updating the keyword tables in both `MathPerceptionAdapter` and `BS4PerceptionAdapter`.

---

## Composition Root Integration

In `infrastructure/composition_root.py`, the fallback is wired as follows:

```python
if driver is not None:
    # Use live‑browser perception (Math or DOM)
    perception_port = MathPerceptionAdapter(driver)
else:
    # Zero‑browser fallback
    perception_port = BS4PerceptionAdapter(UrllibHTTPClient())
    logger.info("build_orchestrator: no browser driver — using BS4PerceptionAdapter")
```

The `ApplicationEngine` receives a `PerceptionPort` — it never knows whether the port is backed by a live browser or static HTML.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the port/adapter pattern that makes the fallback injectable
- [ADR‑003: PRA Loop and State Machines](003_pra_loop_and_state_machine.md) — the `ApplicationState` enum used by `get_current_state()`
- [ADR‑010: Remediation Changelog](010_remediation_changelog.md) — the refactor that turned the BS4 adapter from a stub into a full implementation
- `adapters/secondary/perception/bs4_adapter.py` — the adapter implementation
- `adapters/secondary/network/urllib_http_client.py` — the default HTTP client
- `domain/ports/http_client_port.py` — the `HTTPClientPort` contract