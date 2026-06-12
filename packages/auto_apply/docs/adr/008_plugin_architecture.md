# ADR‑008: Protocol‑Based Plugin Architecture

**Status:** Accepted  
**Date:** 2025‑12‑18  
**Deciders:** Nick Liebmann  
**Technical Story:** As the number of discovery providers, perception adapters, and health monitors grew, it became clear that a formal plugin system would be needed. Rather than introduce a third‑party plugin framework, we realized that the hexagonal architecture already provided a natural plugin mechanism: every port is an extension point, and any class implementing that port can be wired in at the composition root. No additional infrastructure was required.

---

## Context

AutoApply’s architecture (see [ADR‑001](001_hexagonal_architecture.md)) defines a set of abstract ports in `domain/ports/`. Concrete adapters implement those ports and are wired together in the composition root. Early in development, adding a new job board or a new health check required writing an adapter and adding a registration line — nothing more. Over time, the codebase accumulated multiple implementations of each port:

- **Discovery providers:** `GoogleProvider`, `BingProvider`, `IndeedProvider` (and more planned).
- **Perception adapters:** `MathPerceptionAdapter`, `DOMScanner`, `BS4PerceptionAdapter`.
- **Health monitors:** `BrowserHealthMonitor`, `NetworkHealthMonitor`.
- **Interrupt policies:** `ProfileBasedInterruptPolicy`, `NeverInterruptPolicy`, `AlwaysInterruptPolicy`.
- **HTTP clients:** `UrllibHTTPClient` (and an optional `requests`‑based alternative).

Each of these is effectively a plugin — a replaceable component that satisfies a well‑defined contract. The question was whether we needed a formal plugin registry, entry‑point scanning, or lifecycle hooks, or whether the existing architecture was sufficient.

---

## Decision

AutoApply does **not** use a third‑party plugin framework (such as `pluggy` or setuptools entry points). Instead, the hexagonal architecture itself **is** the plugin system.

### The plugin contract

Every port defined in `domain/ports/` is an extension point. Any class that structurally satisfies the port’s Protocol (or inherits from its ABC) is a valid plugin. There is no plugin registry beyond the lists and dictionaries maintained in `infrastructure/composition_root.py`.

To add a new plugin, a developer:

1. Implements the appropriate port in a new file.
2. Imports the class in `composition_root.py`.
3. Appends it to the relevant list or dictionary.
4. (Optionally) adds configuration keys to `runtime_defaults.yaml` if the plugin needs tunable parameters.

No plugin base class, decorator, or registration call is required.

### Extension points

Every port in `domain/ports/` is an extension point. The most commonly extended are:

| Port | What you implement | Example plugins |
|------|-------------------|-----------------|
| `DiscoveryProviderPort` | A new job search source | `GoogleProvider`, `BingProvider`, `IndeedProvider` |
| `PerceptionPort` | A new way to read page state | `MathPerceptionAdapter`, `BS4PerceptionAdapter` |
| `InterruptPolicy` | Custom pause/approval logic | `ProfileBasedInterruptPolicy`, `AlwaysInterruptPolicy` |
| `HTTPClientPort` | A new HTTP backend | `UrllibHTTPClient` |
| `HealthMonitor` | A new health check | `BrowserHealthMonitor`, `NetworkHealthMonitor` |
| `ReasoningPort` | A new form‑planning engine | `FormSolver`, `ClingoFormSolver` |
| `TextGenerationPort` | A new local LLM adapter | `GPT4AllAdapter` |

### Conventions

All plugins must follow these conventions:

1. **No self‑construction.** Plugins receive their dependencies via constructor injection. They never import from `infrastructure/` or instantiate infrastructure objects directly.
2. **Absolute imports only.** `from auto_apply.domain.ports.browser_port import BrowserInterface` — never relative.
3. **Graceful import errors.** If a plugin depends on an optional third‑party library, it guards the import with `try/except` and sets an `available` flag. The composition root skips unavailable plugins with a logged warning.
4. **Daemon threads.** Any background threads must be daemon threads so they do not prevent process exit.
5. **Single entry point.** Plugins expose a single primary method (`run()`, `start()`, `generate()`) that the composition root or orchestrator calls.

### What plugins cannot do

- **Call engines directly.** Engines communicate only through the EventBus. A plugin never imports an engine class.
- **Import from `infrastructure/`.** Only `main.py` and `__main__.py` are allowed to import from `infrastructure/`.
- **Mutate `UserProfile` directly.** Plugins that need to persist state write through a repository port.
- **Block the main thread.** I/O, network calls, and long computations happen on background daemon threads.

---

## Options Considered

### Use a formal plugin framework (pluggy, setuptools entry points)
**Rejected.** These frameworks add a layer of indirection and configuration. In a project where ports already define the contract and the composition root already lists all implementations, the additional machinery provides no benefit. It would also complicate the “worst‑case user first” goal by adding startup overhead and a larger dependency footprint.

### Require plugins to register via a decorator on the class
**Rejected.** A decorator‑based registry hides the list of active plugins from the composition root, making the system’s behaviour harder to audit. The composition root is the single place to see every active component — decorators would distribute that information across the codebase.

### Maintain a plugin registry as a separate YAML file
**Rejected.** This would duplicate the composition root’s role and introduce an additional configuration file that could drift from the actual code. The composition root is already the wiring diagram; adding another layer of indirection would make debugging harder, not easier.

---

## Consequences

### What becomes easier

- **Extensibility:** Adding a new job board or a new browser automation tool requires no framework knowledge — just implement the port and add a registration line.
- **Discoverability:** Every available plugin for a given port is visible in `composition_root.py`. No scanning, no dynamic discovery, no surprises.
- **Testing:** Each plugin can be tested in isolation by mocking the ports it depends on. No plugin runner or framework setup is needed.
- **Removal:** Removing a plugin is a single deletion from `composition_root.py`. No cleanup, no deregistration.

### What becomes harder

- **Third‑party plugin distribution:** The current design requires plugins to be present in the source tree and wired manually. There is no mechanism for a user to drop a plugin file into a directory and have it auto‑discovered. This is a deliberate trade‑off: AA is distributed as a single application, not a plugin host. If third‑party plugins become a requirement, a discovery mechanism can be added without changing the plugin contract — it would simply scan a directory for classes implementing known ports.
- **Plugin ordering:** The order of plugins in a list (e.g., the order of discovery providers) is determined by the composition root. If ordering becomes dynamic (e.g., based on success rates), a `PluginPriority` concept could be introduced, but it is currently unnecessary.

---

## Adding a New Plugin: Worked Example

To add a LinkedIn discovery provider:

1. Create `adapters/secondary/discovery/providers/linkedin.py` implementing `DiscoveryProviderPort`.
2. Import `LinkedInProvider` in `composition_root.py`.
3. Append `LinkedInProvider(browser, context)` to the `providers` list.
4. (Optional) Add LinkedIn‑specific configuration to `runtime_defaults.yaml`.

No other files change. The `DiscoveryEngine` iterates over whatever providers it receives — it has no knowledge of LinkedIn specifically.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the port/adapter pattern that makes this plugin architecture possible
- [ADR‑002: Dependency Injection](002_dependency_injection_refactor.md) — the constructor injection convention that plugins must follow
- `domain/ports/` — all extension points
- `infrastructure/composition_root.py` — the central wiring file where all plugins are registered