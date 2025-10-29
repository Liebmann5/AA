# Contribution Workflow

Thank you for your interest in contributing to the AutoApply Agent! We are excited to build a vibrant open-source community around this project. Whether you're reporting a bug, suggesting a new feature, or writing code, your contributions are valuable.

To ensure a smooth and effective process, we follow a standard workflow based on GitHub Issues and Pull Requests.

---

## Reporting Bugs

If you encounter a bug or an unexpected error, please check the [GitHub Issues page](https://github.com/Liebmann5/AA/issues) to see if it has already been reported.

If it's a new bug, please **[create a new issue](https://github.com/Liebmann5/AA/issues/new)** and provide the following information:

*   **A clear, descriptive title.**
*   **Your operating system** (e.g., Windows 11, macOS Sonoma).
*   **The exact steps to reproduce the bug.**
*   **Any relevant logs or error messages.** You can find the log files in the `logs/` directory at the root of the project. Please copy and paste the relevant sections.

## Suggesting Enhancements or Features

We welcome ideas for new features! If you have a suggestion, please **[create a new issue](https://github.com/Liebmann5/AA/issues/new)** and use the "Feature Request" template.

Provide a clear and detailed description of your idea, including:

*   **The problem you are trying to solve.** What is the user's pain point?
*   **Your proposed solution.** How would this new feature work?
*   **Any alternative solutions** you have considered.

---

## Submitting Code Changes (Pull Requests)

If you would like to contribute code, please follow this standard "Fork & Pull" workflow.

### 1. Fork the Repository

Click the "Fork" button at the top right of the [main repository page](https://github.com/Liebmann5/AA) to create your own copy of the project.

### 2. Clone Your Fork

Clone your personal fork to your local machine:

```bash
git clone https://github.com/Liebmann5/AA.git
cd AA
```

### 3. Set Up Your Development Environment

Before you start coding, you need to install the project with all of its development and documentation dependencies.

```bash
python -m pip install -e ./packages/auto_apply[dev,docs]
```

### 4. Create a New Branch

Create a new branch for your changes. The branch name should be descriptive, such as `fix/login-button-bug` or `feature/add-lever-strategy`.

```bash
git checkout -b your-branch-name
```

### 5. Write Your Code

Make your changes to the code. Please adhere to the project's architectural principles and coding standards. Ensure your code is:

*   **Modular and Testable.**
*   **Well-Documented** with Google-style docstrings for all new classes and functions.

### 6. Run Tests (Coming Soon)

!!! info "Under Construction"
    Our automated test suite is currently under development. In the meantime, please manually test your changes to ensure they work as expected and do not break existing functionality.

### 7. Submit a Pull Request

Once you are happy with your changes, commit them and push them to your fork:

```bash
git add .
git commit -m "A brief, clear description of your changes"
git push origin your-branch-name
```

Finally, go to the original repository on GitHub and click the "New pull request" button. Provide a detailed description of your changes, and link to any relevant issues.

Thank you again for your contribution!

---
## What's Next?
Now that you know the workflow, the next step is to set up your local environment for development and testing.

➡️ **Next: [Setting Up Your Project](02_project_setup.md)**
```

---