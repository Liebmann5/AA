# Setting Up Your Development Environment

This guide provides the complete instructions for setting up a local development environment to work on the AutoApply Agent. This will install the application itself, along with all the tools we use for testing, code formatting, and documentation.

## Prerequisites

*   **Python:** Version 3.9 or newer.
*   **Git:** For cloning the repository.

---

## Step-by-Step Setup

### 1. Fork and Clone the Repository

If you haven't already, please follow the "Fork & Pull" workflow described in the [Contribution Workflow](01_contribution_workflow.md) guide to create your own fork and clone it to your local machine.

```bash
git clone https://github.com/Liebmann5/AA.git
cd AA
```

### 2. Install in Editable Mode with All Extras

This is the most important step. To set up a full development environment, you must install the `auto_apply` package in "editable" mode (`-e`) and include the `[dev,docs]` extras. This command reads the `pyproject.toml` file and installs everything you need.

Run this command from the **root of the `AA` repository**:

```bash
python -m pip install -e ./packages/auto_apply[dev,docs]
```

*   `-e`: Installs the project in **editable mode**. This means your environment will point directly to your source code, so any changes you make will be reflected immediately without needing to reinstall.
*   `[dev,docs]`: This tells `pip` to install all the optional dependencies listed in the `dev` and `docs` groups in your `pyproject.toml` file. This includes `pytest`, `black`, `ruff`, and `mkdocs`.

---

## Recommended Development Workflow

With everything installed, you are now ready to write code. We follow a standard workflow to ensure code quality and consistency.

### 1. Running the Application

You can run the application directly from source using the `python -m` command.

```bash
# To run the GUI
python -m auto_apply

# To run the CLI
python -m auto_apply --cli
```

### 2. Formatting Your Code

We use **Black** as our automatic code formatter. Before you commit any changes, please run Black to ensure your code adheres to the project's style guide.

```bash
# From the root of the repository
python -m black .
```

### 3. Linting Your Code

We use **Ruff** for high-performance linting. It helps catch potential bugs, style issues, and other problems. Run it to check your code for any issues.

```bash
# From the root of the repository
python -m ruff check .
```

### 4. Previewing Documentation

If you are making changes to the documentation, you can run a live-preview server.

```bash
# Navigate to the package directory
cd packages/auto_apply

# Run the server
python -m mkdocs serve
```

---

## What's Next?

Your environment is now fully configured for development. The next step is to learn how to run the project's automated test suite to verify your changes.

➡️ **Next: [Running Tests](03_running_tests.md)**```

---