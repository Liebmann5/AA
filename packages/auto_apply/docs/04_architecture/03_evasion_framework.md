# The Evasion Framework: A Multi-Layered Defense

Modern bot detection is a sophisticated field. To remain undetected, an automation agent cannot simply send requests; it must convincingly mimic a human user across multiple layers of the technology stack. The AutoApply Agent is designed with a professional, multi-layered Evasion Framework to achieve this.

The framework is built on the same principles as our [Core Abstractions](02_core_abstractions.md): an abstract contract (`EvasionStrategyInterface`) defines *what* evasions should be applied, and concrete implementations (`SeleniumEvasionStrategy`, `PlaywrightEvasionStrategy`) define *how* they are applied for a specific browser framework.

## The Four Pillars of Evasion

Our defense-in-depth strategy is organized into four key pillars:

### Pillar 1: Browser Fingerprint Hardening

*   **The Threat:** Websites run JavaScript to collect a "fingerprint" of your browser. They check for hundreds of properties, such as your screen resolution, installed fonts, GPU model (via WebGL), and subtle browser features. A key giveaway is the `navigator.webdriver` flag, which screams "I am automation!"
*   **Our Solution:** We apply "static" evasions *before* the browser navigates to a target site. Using low-level protocols like the Chrome DevTools Protocol (CDP), we inject JavaScript that runs before the page's own scripts. This allows us to:
    *   Set `navigator.webdriver` to `false`.
    *   Spoof the WebGL vendor and renderer to mimic a common GPU.
    *   Add "noise" to Canvas and AudioContext readouts to prevent hashing.
    *   Mask the true number of CPU cores and memory.

### Pillar 2: Behavioral Humanization

*   **The Threat:** Bots move and act with machine-like perfection. Clicks are instantaneous, mouse movements are perfectly straight lines, and typing has a uniform cadence. This behavior is easily detectable.
*   **Our Solution:** We have a dedicated `behavior` module that simulates human-like imperfection and timing.
    *   **Mouse Movements:** Mouse movements follow curved Bezier paths, not straight lines.
    *   **Typing:** A parabolic delay model introduces a natural-seeming cadence between keystrokes.
    *   **Clicks:** Clicks are preceded by slight "overshoots" and pauses to simulate a user aiming.
    *   **Idle Time:** The agent can be instructed to pause and perform random, small "fidgets" with the mouse.

### Pillar 3: Session & Network Integrity

*   **The Threat:** A brand-new browser instance with no cookies, no browsing history, and an IP address from a datacenter is a massive red flag.
*   **Our Solution:** The `SessionManager` gives the agent a sense of history and continuity.
    *   **State Persistence:** Cookies and local storage are saved to a file at the end of a session and reloaded at the start of the next, making the agent appear as a "returning user."
    *   **Intelligent Warmup:** Before visiting a target site, the agent can "warm up" its session by browsing a few unrelated, high-traffic sites (like a news aggregator) to build a more plausible browsing history.
    *   **Proxy Management:** The agent supports using proxies to mask its true IP address.

### Pillar 4: Active Challenge Handling

*   **The Threat:** Even with all the above measures, a site may still present an active challenge, like a CAPTCHA.
*   **Our Solution:** The agent has a proactive detection system.
    *   **Detection:** On every page load, the `detection` module scans the URL, title, and page content for signs of a CAPTCHA.
    *   **Solving (Future):** The framework includes a `CaptchaSolver` interface. The long-term goal is to integrate a free, offline, audio-to-text engine to solve audio reCAPTCHA challenges, adhering to our "100% Free" principle.

---

## What's Next?

➡️ **Next: [Discovery Strategies](04_discovery_strategies.md)**