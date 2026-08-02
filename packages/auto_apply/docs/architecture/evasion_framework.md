# Evasion Framework

Modern job boards are aggressive. They fingerprint your browser, analyse your
mouse movements, time your keystrokes, and check your IP reputation — all to
decide whether you are a human or a bot. AutoApply’s Evasion Framework is a
**multi‑layered defence system** designed to make automated sessions
indistinguishable from human ones, even on the most sophisticated platforms.

The framework is built on the same principles as the rest of AA: every
capability is defined by an abstract port, implemented by a concrete adapter,
and assembled by the composition root. No part of the business logic knows
how evasion works — it simply asks the browser to “click” or “type,” and the
adapter does the rest with realistic timing and behaviour.

---

## The Four Pillars

Our defence‑in‑depth strategy is organised into four independent layers.
Each layer can be enabled, disabled, or configured separately. If a technique
is not available on a given platform, it degrades gracefully — the agent
never crashes because a specific evasion tactic failed.

```
┌─────────────────────────────────────────────────┐
│              Active Challenge Handling           │
│  (CAPTCHA detection → audio solving → manual)   │
├─────────────────────────────────────────────────┤
│           Session & Network Integrity            │
│  (cookies, warmup, proxy, rate limiting)        │
├─────────────────────────────────────────────────┤
│           Behavioural Humanisation               │
│  (mouse curves, typing cadence, idle fidgets)   │
├─────────────────────────────────────────────────┤
│         Browser Fingerprint Hardening            │
│  (WebDriver flag, WebGL, Canvas, fonts, audio)  │
└─────────────────────────────────────────────────┘
```

---

## 1. Browser Fingerprint Hardening

**The Threat:** Websites run JavaScript to collect a “fingerprint” of your
browser — screen resolution, installed fonts, WebGL renderer, CPU core count,
and the infamous `navigator.webdriver` flag that screams “I am automation!”

**Our Solution:** We modify the browser’s JavaScript environment *before*
any page script runs. This is done differently for each framework:

### Selenium (Chrome / Edge)
We use the **Chrome DevTools Protocol (CDP)** to inject scripts via
`Page.addScriptToEvaluateOnNewDocument`. These scripts run in every frame
before any website code, making them undetectable.

| Vector | Technique |
| ------ | --------- |
| `navigator.webdriver` | Set to `false` / `undefined` via `Object.defineProperty`. |
| WebGL vendor & renderer | Override `getParameter` to return common GPU strings (e.g. “NVIDIA GeForce RTX 3060 Ti”). |
| Canvas fingerprinting | Add random noise to `toDataURL` output — the hash changes on every read. |
| Hardware concurrency | Report a common core count (4, 8, or 16) regardless of the real CPU. |
| AudioContext | Add tiny random noise to `getChannelData` to break oscillator‑based fingerprints. |
| Font metrics | Add jitter to `measureText` width — the same font renders at a slightly different width each time. |
| Permissions API | Override `navigator.permissions.query` to return a generic “denied” state for notifications. |

### Selenium (Firefox)
Firefox does not support CDP, so we use a combination of **`about:config`
preferences** (set before launch) and a **large JavaScript payload** injected
at runtime that patches `navigator.plugins`, `screen` properties,
`performance.now`, and the Battery Status API.

### Playwright
Playwright supports **init scripts** — JavaScript that runs before any page
script. We inject the same anti‑fingerprinting payload automatically when the
browser context is created.

### Configuration
All fingerprinting techniques are controlled by a single flag:
`enable_fingerprint_spoofing`. When the environment is low‑resource, this is
automatically disabled to save CPU cycles and memory. Users can also fine‑tune
individual strategies via `runtime_defaults.yaml`:

```yaml
webgl_spoof_strategy: "random"      # "random", "custom", or "off"
canvas_spoof_strategy: "noise"      # "noise" or "off"
spoof_hardware_concurrency: 8       # integer, or null to leave untouched
```

---

## 2. Behavioural Humanisation

**The Threat:** Bots move and type with machine‑like precision. Clicks are
instantaneous, mouse movements are straight lines, and typing has a perfectly
uniform rhythm. Bot‑detection ML models are trained to spot these patterns.

**Our Solution:** The `PageActionService` is the single entry point for
browser interaction, and it applies human‑consistent timing and movement
patterns automatically.

> **Status (Stage 1).** Every **click**, and the pacing between plan steps,
> passes through the tool. Keystrokes, scrolling and pagination still have
> other live paths (the interaction handlers, `InfiniteScrollStrategy`,
> `behavior.human_like_scroll`) and are scheduled to move behind the tool in
> later stages. Treat this section as the target state, not a description of
> today's every code path.

### MICRO Timing — Intra‑Task (milliseconds)
- **Parabolic keystroke delays:** Each character is typed with a pause drawn
  from a parabola‑shaped distribution (most delays cluster around 80 ms, with
  occasional slower pauses). This mimics the natural rhythm of human typing.
- **Mouse movement:** Cursor paths follow curved Bezier curves with two random
  control points. Clicks are preceded by a slight overshoot (moving past the
  target) and a corrective re‑centre — exactly like a human aiming.
- **Random micro‑fidgets:** During idle periods, the mouse twitches by a few
  pixels, simulating the unconscious movements of a hand resting on a mouse.

### MACRO Timing — Inter‑Task (seconds)
- **Post‑navigation pauses:** After loading a page, AA waits 1.5–4.5 seconds
  before interacting — simulating the time a human spends visually scanning
  the page.
- **Between‑field pauses:** After filling one form field, AA pauses 0.3–1.2
  seconds before moving to the next — the time it takes to locate the next
  field on the page.
- **Pre‑submit hesitation:** Before clicking “Submit,” AA pauses for a
  randomised interval — the moment of hesitation a real person has before
  committing.

### Two Execution Strategies

AA provides two strategies, selectable based on the user’s hardware and
risk tolerance:

| Strategy | Behaviour | Use Case |
| -------- | --------- | -------- |
| `StealthHumanStrategy` | Full humanisation: curved mouse paths, parabolic typing, overshoot clicks, micro‑fidgets. | Live job boards (LinkedIn, Greenhouse, Workday). |
| `InstantHeadlessStrategy` | No delays, no curves, direct driver calls. | Headless CI, fast replays, local testing. |

The strategy is injected into `InteractionExecutor` by the composition root.
The engines call the same `click()` and `type_text()` methods regardless —
they never know which strategy is active.

### Adaptive Timing
All timing parameters are read from `CapabilitiesRegistry._effective_config`
at construction. In low‑resource mode, delays are widened to compensate for
slower hardware. Admin policy can enforce a minimum delay via
`min_action_delay_seconds`, preventing users from running AA at aggressive
speeds.

---

## 3. Session & Network Integrity

A brand‑new browser instance with no cookies, no browsing history, and a
datacenter IP address is a massive red flag. Websites track returning
visitors, and a “first‑time visitor” who immediately starts filling forms
is suspicious.

### Session Persistence
The `SessionManager` saves and restores browser state between sessions:

- **Cookies** are serialised to a JSON file and reloaded on the next session.
  AA appears as a returning user, not a brand‑new visitor.
- **Local Storage / Session Storage** are also persisted, so sites that track
  visitors via client‑side storage cannot detect a fresh session.

### Intelligent Warmup
Before navigating to a target job board, AA can “warm up” its session by
browsing a few unrelated, high‑traffic sites (e.g., a news aggregator). It
clicks on random articles, scrolls to simulate reading, and navigates back.
This builds a plausible browsing history and cookie profile in minutes.

### Proxy Management
AA supports HTTP/SOCKS5 proxies. If a proxy is configured, all browser
traffic is routed through it, masking the user’s real IP address. The proxy
can be set in the user profile (`app_config.proxy_server`) or via environment
variables.

### Robots.txt Compliance & Rate Limiting
The `DomainThrottler` enforces a per‑domain delay between requests. It reads
each site’s `robots.txt` and respects the `Crawl‑delay` directive. If the
user has disabled `robots.txt` compliance in their profile, the throttler
uses a configurable default delay instead.

An admin policy can **force** `robots.txt` compliance via
`force_respect_robots_txt: true`, ensuring institutional deployments never
violate website terms of service.

---

## 4. Active Challenge Handling

Even with perfect fingerprinting and human‑like behaviour, a site may still
present an active challenge — a CAPTCHA, a Cloudflare “I’m Under Attack”
page, or a login wall. AA detects these challenges proactively and decides
how to respond.

### Detection
On every page load, the `DefaultDetectionStrategy` runs a series of checks:

1. **URL & Title keywords** — “verify you are human,” “access denied,”
   “attention required,” `/recaptcha/`, `/challenge-platform/`.
2. **JavaScript variables** — presence of `window.grecaptcha`, `window.hcaptcha`,
   `window._cf_chl_opt`.
3. **Iframe sources** — `src` attributes containing `recaptcha` or `hcaptcha`.
4. **Deep DOM text scan** — a single XPath query that checks every visible
   text node on the page for challenge keywords.

Detection is fast — it short‑circuits on the first positive result.

### Resolution
When a challenge is detected, AA publishes a `CAPTCHA_DETECTED` event on the
EventBus. The orchestrator pauses the current task and dispatches a
`HANDLE_CAPTCHA` work unit.

AA attempts automatic resolution first:

- **Audio reCAPTCHA:** The `CaptchaResolutionService` clicks the “Audio”
  button on the reCAPTCHA widget to switch modes. The audio file can be
  downloaded and processed with an offline speech‑to‑text engine (`vosk`).
  This feature is experimental and bundled in the `[captcha]` extra.

If automatic resolution fails (or if the `[captcha]` extra is not installed),
AA escalates to **manual resolution**:

1. The orchestrator publishes `CAPTCHA_REQUIRES_MANUAL_SOLVE`.
2. The GUI displays a “Please solve the CAPTCHA” message, or the CLI prompts
   the user.
3. The agent pauses and waits for the user to solve the challenge in the
   browser window.
4. Once solved, the user clicks “Continue” (or presses Enter in the CLI), and
   the agent resumes.

This two‑tier approach ensures that AA never gets permanently stuck on a
CAPTCHA — it either solves it automatically or asks for human help.

### Detection Configuration
Challenge detection keywords are stored in a JSON configuration file
(`detection_config.json`) that can be updated without code changes. New
CAPTCHA providers or block‑page patterns can be added by editing this file.

---

## Architecture & Integration

The evasion framework is fully decoupled from the business logic.

- **`EvasionManager`** (adapters layer) is the high‑level controller. It
  provides `check_page_safety()` — a single method the engines call after
  navigation.
- **`PageActionService`** (application services) is the unified interaction
  API. Engines receive it as `interaction_port`; a call to
  `interaction_port.click(btn)` delegates to the tool, which applies
  human‑like movement automatically. The composition root constructs it with
  a namespaced seeded RNG (`interaction.pacing`) whenever a driver exists.
- **`SessionManager`** (adapters layer) manages persistent browser state.
  It is used as a context manager around the browser session.

The composition root wires everything:

```python
# Evasion is applied automatically — engines don't see it
page_action = PageActionService(browser, registry)
engine = ApplicationEngine(
    perception_port=perception_port,
    interaction_port=InteractionExecutor(browser, strategy=StealthHumanStrategy()),
    reasoning_port=FormSolver(profile),
)
```

Engines call `page.click(element)` — they don't know or care that the click
travels along a Bezier curve with a parabolic pre‑click hesitation. That is
the adapter’s job.

---

## Graceful Degradation

Every evasion technique is optional. If a library is missing or a platform
doesn't support a technique, AA continues without it.

| If … | AA will … |
| ---- | --------- |
| Playwright is not installed | Use Selenium with CDP‑based fingerprinting. |
| Selenium is not installed | Use Playwright with init‑script fingerprinting. |
| Neither is installed | Skip fingerprinting and behavioural humanisation entirely; still functional. |
| Low‑resource mode is active | Disable fingerprint spoofing (too CPU‑intensive) and widen delays. |
| Admin policy enforces a minimum delay | Use the admin's delay floor; user can set longer but not shorter. |

---

## Summary

AA’s Evasion Framework operates at four layers:

1. **Fingerprint Hardening** — makes the browser look like a normal user’s
   Chrome/Firefox, not an automation tool.
2. **Behavioural Humanisation** — makes interactions *feel* human: curved
   mouse paths, parabolic typing, random pauses.
3. **Session & Network Integrity** — maintains persistent cookies, warms up
   sessions, respects `robots.txt`, and routes through proxies.
4. **Active Challenge Handling** — detects CAPTCHAs, attempts automatic
   resolution, and falls back to manual solving.

Together, these layers give AA the best possible chance of operating
undetected — on any platform, with any browser, for any user.

---

## Next Steps

- [Discovery Strategies](discovery_strategies.md) — how AA uses the hardened
  browser to search for jobs.
- [Application Engine](application_engine.md) — how the form‑filling engine
  uses `PageActionService` to interact like a human.
- [Browser Cascade](browser_cascade.md) — how the right browser is selected
  for the evasion strategy to work.