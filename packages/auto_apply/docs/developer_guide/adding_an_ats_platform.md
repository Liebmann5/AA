# Adding an ATS Platform

AutoApply can identify and adapt to dozens of Applicant Tracking Systems
(ATS) — Greenhouse, Lever, Workday, Taleo, iCIMS, Ashby, and more.  The
magic that makes this possible is the **ATS Registry**: a collection of
YAML files that describe each platform’s URL patterns, form selectors, and
page‑state signals.

Adding a new ATS platform requires **zero Python code changes**.  You
create one YAML file, restart AA, and the registry picks it up
automatically.  This guide walks you through the entire process, from
understanding the descriptor format to testing your new platform.

---

## How the Registry Works

When AA starts, `ATSRegistry` (in `adapters/secondary/discovery/ats_registry.py`)
scans the `resources/ats/` directory and loads every `*.yaml` file.  Each
file is parsed into an `ATSDescriptor` — a frozen dataclass that holds:

- **URL patterns** — glob‑style strings that match the platform’s job
  application URLs.  These are compiled into case‑insensitive regular
  expressions at load time.
- **Login wall signals** — text snippets that indicate the page is blocked
  behind a login.
- **Success signals** — text that confirms a submission was successful.
- **CSS selectors** — the form root and the submit / next button, used by
  the Application Engine for platform‑specific form handling.
- **Multi‑step flag** — whether the platform uses a multi‑page wizard.

The registry exposes two methods:

- `match(url)` → returns the `ATSDescriptor` for the matched platform, or
  `None`.
- `all_descriptors()` → returns all loaded descriptors, used by discovery
  providers to build site‑filter lists.

---

## 1. Understand the Descriptor Fields

Here is a complete descriptor, annotated with explanations:

```yaml
# resources/ats/example.yaml

name: example                         # Lowercase canonical name (e.g. "greenhouse")
description: >                        # Optional human-readable description
  Example ATS used by mid‑sized tech companies.  Single‑page forms.

url_patterns:                         # Glob patterns — wildcards become regex ".*"
  - "*.example.com/jobs/*/apply*"     # Matches subdomains like "careers.example.com/jobs/123/apply"
  - "jobs.example.com/*"              # Matches any path under jobs.example.com

login_wall_signals:                   # Lowercased text snippets that mean "login required"
  - "sign in to continue"
  - "create an account to apply"
  - "log in to apply"

success_signals:                      # Lowercased text that confirms a successful submission
  - "application submitted"
  - "thank you for applying"
  - "we've received your application"

form_root_selector: "#application-form"     # CSS selector for the element that roots the form
submit_button_selector: >                    # CSS selector for the submit / next button
  button[type='submit'],
  input[type='submit']

multi_step: false                     # true if the platform uses a multi‑page wizard
```

### Field details

| Field | Required | Purpose |
| ----- | -------- | ------- |
| `name` | **Yes** | Lowercase identifier. Must be unique among all descriptors. Used in logs and telemetry. |
| `description` | No | Human‑readable context for maintainers. Not used at runtime. |
| `url_patterns` | **Yes** | One or more glob patterns. `*` matches any characters including `/` and `.`. The scheme (`https://`) is stripped before matching. |
| `login_wall_signals` | No | If the page contains any of these phrases, the Application Engine will report `LOGIN_WALL` and abort. |
| `success_signals` | No | If the confirmation page contains any of these phrases, AA considers the application successful. |
| `form_root_selector` | No | CSS selector for the form container. Defaults to `"form"`. Used to scope field searches. |
| `submit_button_selector` | No | CSS selector for the submit or next button. Defaults to `"button[type='submit']"`. |
| `multi_step` | No | Set to `true` if the platform splits the application across multiple pages (like Workday or Taleo). |

---

## 2. Create Your YAML File

1.  Navigate to `packages/auto_apply/src/auto_apply/resources/ats/`.
2.  Create a new file named after the platform in lowercase, with a `.yaml`
    extension — for example, `myplatform.yaml`.
3.  Copy the template above, or use an existing descriptor (like
    `greenhouse.yaml`) as a starting point.
4.  Fill in the fields with the platform’s actual URL patterns, signals,
    and selectors.

!!! tip
    Start with just `name` and `url_patterns`.  The other fields are
    optional and can be added iteratively as you test.  AA will work with
    partial descriptors — it simply won't have platform‑specific selectors
    or signals until you add them.

---

## 3. Writing URL Patterns

URL patterns use a simple **glob** syntax:

- `*` matches any run of characters, including dots and path separators.
- The scheme (`https://`) is stripped before matching, so do not include it.
- Patterns are case‑insensitive.

Internally, globs are converted to regular expressions:

| Glob | Regex | Matches |
| ---- | ----- | ------- |
| `*.greenhouse.io/jobs/*` | `.*\.greenhouse\.io/jobs/.*` | `boards.greenhouse.io/jobs/12345` |
| `jobs.lever.co/*/apply` | `jobs\.lever\.co/.*/apply` | `jobs.lever.co/acme/apply` |
| `*.myworkdayjobs.com/*` | `.*\.myworkdayjobs\.com/.*` | `acme.myworkdayjobs.com/job/abc` |

### Tips for good patterns

- **Be specific enough to avoid false matches.**  `*.example.com/*` will
  match every page on the domain, including the homepage.  Add path segments
  that are unique to job applications: `*.example.com/jobs/*/apply`.
- **Use multiple patterns if the platform has multiple URL structures.**
  For example, Lever has both `jobs.lever.co/*/apply` and
  `jobs.eu.lever.co/*/apply`.
- **Test your patterns** with the `--check-config` flag (see Step 5).

---

## 4. Adding Signals and Selectors

### Login wall signals

These are lowercased text snippets that, if found in the page’s visible
text, indicate the user must log in before proceeding.  Look at the login
page for common phrases like "Sign in to continue" or "Create an account."
AA scans for these phrases and, if found, reports `LOGIN_WALL` to the
orchestrator so the job can be skipped.

### Success signals

These are lowercased text snippets that appear on the confirmation page
after a successful submission.  Look for phrases like "Application
submitted," "Thank you for applying," or "We've received your application."
AA uses these to verify that the submission was successful.

If the platform uses a unique CSS class or element ID instead of text, you
can provide a CSS selector as a signal by prefixing it with `selector:`
(e.g. `"selector:.post-apply-confirmation"`).  However, text‑based signals
are preferred because they are more robust against layout changes.

### Form root selector

A CSS selector that identifies the outermost container of the application
form.  This is used to scope field searches.  Common values:

- `#application_form` (Greenhouse)
- `.application-form` (Lever)
- `[data-automation-id='applicationForm']` (Workday)

If you are unsure, inspect the page with browser DevTools and look for the
element that wraps all the input fields and the submit button.

### Submit button selector

A CSS selector for the button that submits the form or moves to the next
step.  This is used by the `ApplicationEngine` to locate the correct button
when multiple buttons exist on the page.  Common values:

- `button#submit_app` (Greenhouse)
- `button[data-qa='btn-submit-application']` (Lever)
- `[data-automation-id='pageFooterNextButton']` (Workday)

You can provide multiple selectors separated by commas, just like in CSS.

### Multi‑step flag

Set to `true` if the application spans multiple pages, each with its own
"Next" button and a final "Submit" on the last page.  This tells the
`ApplicationEngine` to expect page transitions and to look for "Next" or
"Continue" buttons between steps.  Set to `false` (the default) for
single‑page forms.

---

## 5. Testing Your Descriptor

1.  **Restart AA.**  The registry loads all `*.yaml` files at startup, so
    your new file will be picked up automatically.
2.  **Run `--check-config`** to verify the registry loaded it:
    ```bash
    python -m auto_apply --check-config
    ```
    You should see output similar to:
    ```
    ✅ ATSRegistry loaded 7 descriptors (including 'myplatform')
    ```
    If the file is malformed, AA will log a warning and skip it.  Check the
    log file (`data/logs/app.log`) for details.
3.  **Test URL matching manually** (if you have a Python shell):
    ```python
    from auto_apply.adapters.secondary.discovery.ats_registry import ATSRegistry
    registry = ATSRegistry()
    d = registry.match("https://careers.myplatform.com/jobs/123/apply")
    print(d.name if d else "No match")
    ```
4.  **Run a discovery session** with a company that uses this ATS.  Check
    the session logs to confirm that AA identified the platform correctly
    (look for `ATSRegistry.match | ats=myplatform url=...`).

---

## 6. How the Registry Is Used

Once your descriptor is loaded, it is automatically used by:

### Discovery providers

`GoogleProvider.find_company_career_page()` calls `_ats_site_filters(registry)`,
which extracts the root domain from every descriptor’s URL patterns.  Your
new platform’s domain is automatically included in career‑page search
queries — no provider code changes needed.

### Application Engine (future integration)

The `ApplicationEngine` can look up `submit_button_selector` and
`form_root_selector` from the matched `ATSDescriptor`, allowing
platform‑specific form handling without hardcoded selectors.  This
integration is currently being developed; in the meantime, the engine
uses robust generic heuristics that work on most platforms.

---

## 7. Troubleshooting

| Problem | Likely cause | Solution |
| ------- | ------------ | -------- |
| Descriptor not loaded (not in `--check-config` output) | File is not valid YAML or has a syntax error | Run `python -m yaml myplatform.yaml` to validate the syntax. |
| `match()` returns `None` for a known URL | Glob pattern doesn't match the URL format | Check that the pattern accounts for subdomains, path structure, and any query parameters.  Use the Python shell to test (see Step 5). |
| Login wall not detected | Signal text doesn't appear on the page, or is in a different case | Add the exact text as it appears on the page, all lowercased.  Multiple variations can be listed. |
| Success not detected | Confirmation text is loaded dynamically via JavaScript | The `BS4PerceptionAdapter` (static fallback) cannot see JavaScript‑rendered content.  If possible, find a static text signal; otherwise, the signal will only work with the live‑browser adapters. |

---

## 8. Contributing Your Descriptor

If you have created a descriptor for a new ATS platform, please consider
contributing it back to the project!  Open a pull request with your YAML
file added to `resources/ats/`.  Follow the [Contribution Workflow](contribution_workflow.md)
and include:

- The YAML file itself.
- A brief description of how you tested it.
- Any notes on platform quirks (session timeouts, unusual field names,
  CAPTCHA frequency, etc.) in the `notes` field of the YAML — this helps
  future maintainers.

---

## Next Steps

- [Architecture Overview](architecture_overview.md) — understand the
  hexagonal layers and the composition root.
- [Contribution Workflow](contribution_workflow.md) — how to submit your
  new descriptor as a pull request.
- [Discovery Strategies](../architecture/discovery_strategies.md) — how
  the registry is used by job search providers.