# ADR‑004: YAML‑Driven ATS Platform Registry

**Status:** Accepted  
**Date:** 2025‑10‑28  
**Deciders:** Nick Liebmann  
**Technical Story:** AutoApply needs to interact with many different Applicant Tracking Systems (ATS) — Greenhouse, Lever, Workday, Taleo, iCIMS, Ashby, and dozens more. Each platform has unique URL patterns, login‑wall signals, success confirmation text, and DOM selectors. Before the registry, this knowledge was scattered across provider files and hardcoded into search queries, making it impossible to add a new ATS without editing multiple Python source files.

---

## Context

The Discovery, Vetting, and Application engines all need to answer questions like:

- Given a job URL, which ATS platform am I on?
- What CSS selector should I use for the submit button on this platform?
- Is this platform known to use multi‑step application wizards?
- What text on the confirmation page indicates a successful submission?

Before the registry, answers to these questions were hardcoded in at least three locations:

1.  **`IndeedProvider._construct_url()`** — had Indeed‑specific URL structures baked in.
2.  **`GoogleProvider.find_company_career_page()`** — used a hardcoded list of `["greenhouse.io", "lever.co", "workday.com"]` to filter search results.
3.  **The Application Engine** — had no way to programmatically ask “what is the submit button selector for this platform?” — it relied on generic heuristics.

Adding a new ATS required editing multiple Python files and re‑deploying the application.

---

## Decision

All ATS‑specific knowledge is stored in **YAML descriptor files** under `resources/ats/`. A central `ATSRegistry` class loads these files at startup and compiles the URL patterns into case‑insensitive regular expressions. The registry exposes two methods:

- `match(url)` → returns an `ATSDescriptor` for the matched platform, or `None`.
- `all_descriptors()` → returns all loaded descriptors, used by discovery providers to build site‑filter lists.

### ATSDescriptor

```python
@dataclass(frozen=True)
class ATSDescriptor:
    name: str                              # "greenhouse", "lever", ...
    url_patterns: tuple[str, ...]          # glob-style patterns → compiled to regex
    login_wall_signals: tuple[str, ...]    # lowercased text indicating auth required
    success_signals: tuple[str, ...]       # lowercased text indicating success
    form_root_selector: str                # CSS selector for the form root
    submit_button_selector: str            # CSS selector for the submit / next button
    multi_step: bool                       # True if the ATS uses a wizard pattern
```

### YAML File Format

Each ATS gets its own file. Example for Greenhouse:

```yaml
name: greenhouse
url_patterns:
  - "*.greenhouse.io/jobs/*"
  - "boards.greenhouse.io/*/jobs/*"
  - "app.greenhouse.io/*/jobs/*"
login_wall_signals:
  - "sign in to continue"
  - "log in to apply"
success_signals:
  - "your application has been submitted"
  - "thank you for applying"
form_root_selector: "#application_form"
submit_button_selector: "button#submit_app, input[type='submit']"
multi_step: false
```

### Regex Compilation

The glob‑style patterns (`*.greenhouse.io/jobs/*`) are converted to case‑insensitive regex at load time by escaping regex meta‑characters and replacing `\*` with `.*`. The URL scheme is stripped before matching. This gives more robust matching than the earlier `fnmatch` approach, correctly handling subdomains, multiple path segments, and URL parameters.

### How Providers Use the Registry

`GoogleProvider.find_company_career_page()` no longer uses a hardcoded site‑filter list. Instead, it calls `_ats_site_filters(registry)`, which extracts root domains (e.g. `"greenhouse.io"`) from every loaded descriptor’s URL patterns. Adding a new ATS descriptor automatically includes its domain in company career‑page searches — zero code changes required.

---

## Options Considered

### Keep hardcoded per‑platform logic in each provider and engine
**Rejected.** This was the status quo. It scattered knowledge across the codebase, made adding a new ATS an error‑prone multi‑file edit, and prevented the Application Engine from leveraging platform‑specific selectors.

### Store descriptors in a Python module as nested dictionaries
**Rejected.** While functional, this still requires a code change (and thus a redeployment) to add or modify an ATS. YAML files are editable by non‑developers, can be validated with a simple schema check, and are reloaded on every startup without recompilation.

### Use a database table for ATS descriptors
**Rejected.** This would introduce a database dependency for what is essentially static configuration data. The YAML files are part of the repository, version‑controlled, and require no database connection to read.

### Use fnmatch for URL pattern matching
**Rejected after initial implementation.** The early version of `ATSRegistry` used Python’s `fnmatch` module, but this proved insufficient for patterns containing dots and wildcards in arbitrary positions. The current implementation compiles patterns to compiled regular expressions, which gives full control over matching semantics and is also faster for repeated lookups.

---

## Consequences

### What becomes easier

- **Adding a new ATS:** Create a single YAML file in `resources/ats/` with the platform’s URL patterns, selectors, and signal texts. Restart AA. No Python changes required.
- **Updating a platform:** Edit the YAML file. The changes take effect on the next launch. No code redeployment needed.
- **Discovery provider integration:** All providers automatically benefit from new ATS descriptors through `_ats_site_filters()` — their search queries are updated without touching provider code.
- **Application Engine integration:** The engine can look up `submit_button_selector` and `form_root_selector` from the matched `ATSDescriptor`, allowing platform‑specific form handling without hardcoded selectors.
- **Validation:** YAML files can be validated with a simple schema check at startup. Malformed files are skipped with a warning — they never crash the application.

### What becomes harder

- **Pattern debugging:** Globs compiled to regex can produce unexpected matches if the glob syntax is ambiguous. The `_compile_patterns` function includes logging to help diagnose mis‑matching.
- **Descriptor completeness:** The registry is only as good as the YAML files it loads. An ATS with missing or outdated selectors will not be correctly identified. Contributors must keep descriptors in sync with platform changes.

---

## Current Coverage

The `resources/ats/` directory contains descriptors for the six most common ATS platforms:

- Greenhouse
- Lever
- Workday
- Taleo
- iCIMS
- Ashby

Additional platforms can be added by contributors following the documented format.

---

## References

- [ADR‑001: Hexagonal Architecture](001_hexagonal_architecture.md) — the port/adapter pattern that makes the registry injectable
- [ADR‑008: Plugin Architecture](008_plugin_architecture.md) — how the registry functions as an extension point
- `resources/ats/*.yaml` — all ATS descriptor files
- `adapters/secondary/discovery/ats_registry.py` — the `ATSRegistry` implementation
- `domain/ports/ats_port.py` — the `ATSDescriptor` dataclass and `ATSPort` Protocol
- `adapters/secondary/discovery/providers/google.py` — example of a provider consuming the registry via `_ats_site_filters()`