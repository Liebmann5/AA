# Running Tests

AutoApply’s test suite is built on **pytest**.  Tests live in the `tests/`
directory and mirror the source tree.  We use `MagicMock` extensively to
keep tests fast and isolated — no real browser, database, or network is
needed for unit tests.

---

## Quick Start

Run the full test suite from the repository root:

```bash
uv run pytest tests/ -x -q
```

- `-x` stops after the first failure (useful during development).
- `-q` keeps output quiet unless something goes wrong.

If you want verbose output to see each test name:

```bash
uv run pytest tests/ -v
```

---

## Test Organisation

```
tests/
├── adapters/
│   ├── test_bs4_adapter.py
│   ├── test_cli_wizard.py
│   ├── test_discovery_providers.py
│   ├── test_math_dom_adapter.py
│   ├── test_math_perception_adapter.py
│   └── test_urllib_http_client.py
├── application/
│   ├── test_applications_use_case.py
│   └── test_vetting_use_case.py
├── domain/
│   ├── test_convex_hull.py
│   ├── test_entropy.py
│   ├── test_honeypot_detection.py
│   ├── test_label_input_pairing.py
│   ├── test_occlusion.py
│   ├── test_structural_hashing.py
│   └── test_transformations.py
├── research/
│   ├── test_research_anonymizer.py
│   ├── test_research_collector.py
│   └── test_research_pipeline.py
├── workflows/
│   ├── test_applications_workflow.py
│   ├── test_discovery_workflow.py
│   └── test_vetting_workflow.py
├── conftest.py             # shared fixtures (NodeMap, DOM node builders)
└── smoke_run.py            # quick wiring smoke test
```

Each file tests a single module or a small cluster of related modules.
Tests for domain services (convex hull, entropy, occlusion, etc.) are
pure mathematics — they need no mocking at all.

---

## Running Specific Tests

Run a single test file:

```bash
uv run pytest tests/domain/test_convex_hull.py -v
```

Run a single test function:

```bash
uv run pytest tests/domain/test_convex_hull.py::test_square_four_corners -v
```

Run all tests matching a keyword (substring match on test name):

```bash
uv run pytest tests/ -k "honeypot" -v
```

Run all tests in a specific directory:

```bash
uv run pytest tests/application/ -v
```

---

## Test Markers

We use pytest markers to categorise tests by speed and scope.  You can
filter by marker with the `-m` flag.

| Marker | Meaning | Example command |
| ------ | ------- | --------------- |
| *(no marker)* | **Unit tests** — fast, no I/O, run in milliseconds. | `uv run pytest tests/` |
| `integration` | **Integration tests** — use a real `:memory:` SQLite database, spin up mock orchestrators. Slower but still no network. | `uv run pytest tests/ -m "integration"` |
| `slow` | **Smoke / end‑to‑end tests** — may require a real browser or an internet connection. Run manually before releases. | `uv run pytest tests/ -m "slow"` |

Currently, most tests are unit tests and use no markers.  The `integration`
and `slow` markers are being added as the test suite grows.  You can mark
a test with:

```python
import pytest

@pytest.mark.integration
def test_orchestrator_retry_logic():
    ...
```

To skip all integration tests during rapid development:

```bash
uv run pytest tests/ -m "not integration"
```

---

## Test Fixtures

Shared fixtures are defined in `tests/conftest.py` (available to every
test file automatically) and in the `tests/*/conftest.py` files (available
to tests in that directory).

### Key fixtures in `tests/conftest.py`

| Fixture | What it provides |
| ------- | ---------------- |
| `NodeMap` | A dict‑like class that uses `id()` for keys, enabling `DOMNode` objects (which are unhashable) to serve as dictionary keys for parent maps.  Used extensively in occlusion and honeypot tests. |
| `make_geometry` | A factory function `make_geometry(x, y, w, h)` returning a `Geometry`. |
| `visible_geometry` | A pre‑built `Geometry(x=100, y=100, width=200, height=40)`. |
| `zero_geometry` | A `Geometry` with zero area (used for hidden‑element tests). |
| `offscreen_geometry` | A `Geometry` positioned far off‑screen. |
| `input_node` | A pre‑built `DOMNode` representing a visible text input. |
| `label_node` | A pre‑built `DOMNode` representing a label with text. |
| `simple_form_root` | A minimal form tree: one `label` + one `input` as siblings under a `form`. |

### Key fixtures in `tests/workflows/conftest.py`

| Fixture | What it provides |
| ------- | ---------------- |
| `mock_profile` | A fully valid `UserProfile` with minimal data. |
| `sample_job` | A minimal `Job` object (`"Software Engineer"` at `"Acme Corp"`). |
| `mock_event_bus` | A `MagicMock` that captures published events in a list. |
| `mock_job_repo` | A `MagicMock` satisfying `JobRepositoryPort`. |
| `mock_task_queue` | A `MagicMock` satisfying `WorkQueuePort`. |
| `mock_text_matcher` | A `MagicMock` that returns sensible defaults (similarity 0.85, matches "Software Engineer"). |
| `mock_perception_port` | A `MagicMock` that returns a pre‑built `UIModel` with text content. |
| `mock_interaction_port` | A `MagicMock` that accepts click/fill calls. |
| `mock_browser` | A `MagicMock` satisfying `BrowserInterface`. |

These fixtures make it trivial to set up workflow tests — just request
them as arguments and they are ready to use.

---

## Writing New Tests

### Where to put your test

Create a new file in the appropriate `tests/` subdirectory.  The file name
must start with `test_`.  For example, a test for a new vetting filter
would go in `tests/domain/test_my_new_filter.py`.

### Test structure

```python
"""Unit tests for domain/vetting/my_new_filter.py."""

import pytest
from auto_apply.domain.vetting.my_new_filter import MyNewFilter
from auto_apply.domain.models.job import Job


class TestMyNewFilter:
    """Group related tests in a class for clarity."""

    def test_passes_when_condition_met(self):
        """A descriptive name — reads like a sentence."""
        job = Job(title="Engineer", company="Acme", url="https://...", source="test")
        profile = ...  # build or mock a UserProfile

        filter = MyNewFilter(profile)
        passed, reason = filter.filter(job)

        assert passed
        assert "ok" in reason.lower()

    def test_fails_when_condition_not_met(self):
        ...
```

### Use existing fixtures

Prefer the shared fixtures in `conftest.py` over creating your own mocks
from scratch.  This keeps tests consistent and reduces boilerplate.

```python
def test_my_filter_with_mock_profile(mock_profile, sample_job):
    filter = MyNewFilter(mock_profile)
    passed, _ = filter.filter(sample_job)
    assert passed
```

### Mocking external dependencies

If your component depends on a port (e.g. `JobRepositoryPort`), inject a
`MagicMock` and configure it to return the data your test needs:

```python
from unittest.mock import MagicMock

def test_throttling_blocks_duplicate():
    mock_repo = MagicMock()
    mock_repo.was_applied.return_value = True

    filter = ThrottlingFilter(profile, mock_repo)
    passed, reason = filter.filter(job)

    assert not passed
    assert "already applied" in reason.lower()
```

No database, no filesystem, no network.  The mock verifies the filter’s
logic, not the database driver.

### Testing exceptions

Use `pytest.raises` to verify that the right exception is raised:

```python
def test_raises_on_invalid_input():
    with pytest.raises(ValueError, match="invalid"):
        my_function("bad_input")
```

### Parametrising tests

When testing a function with many input variations, use `@pytest.mark.parametrize`:

```python
@pytest.mark.parametrize("amount,expected", [
    (30000,  "<50k"),
    (80000,  "75k-100k"),
    (175000, "150k-200k"),
])
def test_salary_buckets(amount, expected):
    assert generalize_salary(amount) == expected
```

---

## Continuous Integration

We use **GitHub Actions** to run the test suite on every pull request and
push to `dev` and `main`.  The CI pipeline:

1. Checks out the code.
2. Installs `uv` and runs `uv sync`.
3. Runs `ruff check .` (linting).
4. Runs `black --check .` (formatting).
5. Runs `uv run pytest tests/ -x -q` (tests).
6. (Future) Runs integration and smoke tests on a schedule.

The CI configuration lives in `.github/workflows/ci.yml`.  You do not
need to run CI locally, but running `uv run pytest tests/ -x -q` before
pushing will save you from waiting for CI to catch a broken test.

### Pre‑commit hooks (optional)

If you want to automate formatting and linting, add a `.pre-commit-config.yaml`
to your local clone:

```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 26.3.1
    hooks:
      - id: black
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.10
    hooks:
      - id: ruff
```

Then run `pre-commit install`.  Every commit will be checked automatically.

---

## Tips

- **Run tests frequently while you code.**  The suite is fast — most unit
  tests complete in under a second.
- **Use `-x` during development** to stop at the first failure and fix it
  immediately.
- **Use `--lf` to rerun only the tests that failed last time:**
  ```bash
  uv run pytest tests/ --lf
  ```
- **If a test fails and you don't understand why**, add `--pdb` to drop
  into the Python debugger at the point of failure:
  ```bash
  uv run pytest tests/domain/test_entropy.py --pdb
  ```
- **Keep tests deterministic.**  Avoid `random` without a fixed seed, and
  never depend on real network calls or system time.  Use `MagicMock` for
  anything external.
- **If you fix a bug, add a test that reproduces it** before applying the
  fix.  This prevents regressions.