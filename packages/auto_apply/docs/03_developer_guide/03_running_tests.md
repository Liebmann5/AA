# Running Tests

Automated testing is a cornerstone of this project's commitment to quality and stability. We use the **pytest** framework to write and run our tests.

Running the test suite is a critical step that you must perform before submitting any pull request. This ensures that your changes have not accidentally broken any existing functionality (this is known as a "regression").

## Prerequisites

You must have a full development environment set up, as described in the [Project Setup Guide](02_project_setup.md). This ensures that `pytest` and all other necessary development tools are installed.

---

## How to Run the Test Suite

Running the entire test suite is a single, simple command.

### 1. Navigate to the Package Root

Open your terminal and make sure you are in the `packages/auto_apply` directory. This is the directory that contains the `pyproject.toml` and the `src/` folder.

### 2. Execute Pytest

Run the following command:

```bash
python -m pytest```

*   `python -m pytest`: This tells Python to find and run the `pytest` module. It will automatically discover all the test files (named `test_*.py`) inside the `tests/` directory and execute them.

### Understanding the Output

If all tests pass, you will see a summary at the end of the output that looks something like this:

```
========================= 25 passed in 5.31s =========================
```

The green "passed" message indicates that your changes are safe and have not introduced any regressions.

If any tests fail, you will see a detailed error report in red. This report will show you which test failed and provide a "traceback" to help you find the exact line of code that caused the problem. You must fix all failing tests before submitting your code.

---

## Writing New Tests

If you are contributing a new feature, you should also add new tests for it.

*   All test files must be placed in the `tests/` directory.
*   The test file's name must start with `test_` (e.g., `test_new_feature.py`).
*   Inside the file, each test function's name must also start with `test_` (e.g., `def test_something_happens():`).

Following this convention allows `pytest` to discover and run your new tests automatically.

---

This completes the Developer Guide! You now have all the information you need to set up your environment, contribute code, and verify your changes. The next section provides a deep dive into the project's architecture.