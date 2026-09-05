# AutoApply Agent (UNDER-CONSTRUCTION)

[![Python Version][python-badge]][python-link]
[![License: MIT][license-badge]][license-link]
[![Code Style: Black][black-badge]][black-link]
[![Docs][docs-badge]][docs-link]

An autonomous, open-source agent for discovering, vetting, and applying for jobs, built with a professional-grade, framework-agnostic architecture.

---

## Agent in Action

The AutoApply Agent intelligently navigates the web, identifies job opportunities based on your profile, and handles the application process from start to finish.

![AutoApply Agent in Action](packages\auto_apply\aa_running_visual.gif)

## ✨ Key Features

*   **🤖 Autonomous State-Driven Operation:** The agent is powered by a high-level state machine (`AgentOrchestrator`) that manages its entire lifecycle, making its operations robust, predictable, and resilient to errors.

*   **🧠 Intelligent Job Vetting:** Using a lightweight, offline AI model (a Sentence Transformer), the agent analyzes job titles for conceptual similarity to ensure a "Two-Way Fit." It understands the difference between "Principal Engineer" and "School Principal," preventing mismatched applications.

*   **🛡️ Advanced Evasion Framework:** A multi-layered defense system designed to mimic human behavior and avoid bot detection. This includes:
    *   **Fingerprint Hardening:** Masks browser properties like `navigator.webdriver`, WebGL, and Canvas.
    *   **Behavioral Humanization:** Simulates human-like mouse movements, typing cadence, and idle time.
    *   **Session Integrity:** Persists cookies and storage between runs and can "warm up" sessions to appear as a returning user.

*   **🔌 Framework-Agnostic Design:** Built on a core `BrowserInterface`, the agent is not tied to a single automation library. It currently supports both **Selenium** and **Playwright** and can be extended to support others.

*   **🚀 Resilient & Self-Healing Scraping:** The `AdaptiveSearchManager` uses a pipeline of strategies to find jobs. If one strategy fails, it automatically tries the next. Its heuristic engine can dynamically find job containers on a page even if the website's layout changes.

*   **💯 100% Free & Open Source:** The agent is committed to using only free, open-source, and offline-first tools, ensuring it is accessible to everyone.

---

## 🚀 Getting Started

These instructions will get the agent running on your local machine.

### Prerequisites

*   **Python 3.10+**
*   **Git**

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Liebmann5/AA.git
    cd AA
    ```

2.  **Install the project:**
    This command installs the `auto_apply` package in editable mode along with all its required dependencies.
    ```bash
    python -m pip install -e ./packages/auto_apply
    ```

## Usage

The agent can be run with a Graphical User Interface (GUI) or directly from the command line (CLI).

*   **To launch the GUI (Recommended):**
    ```bash
    python -m auto_apply
    ```

*   **To launch the CLI:**
    ```bash
    python -m auto_apply --cli
    ```

The first time you run the agent, a **Setup Wizard** will guide you through configuring your `default_profile.json` file.

---

## 📚 Documentation

For a complete guide to installation, configuration, and the project's architecture, please **[view the full documentation site](https://github.com/Liebmann5/AA/)**.  <!-- TODO: Update this link when you deploy your docs -->

The documentation includes:
*   A **User Guide** for non-technical users.
*   A **Developer Guide** for contributors.
*   A deep dive into the **Architecture**, explaining the state machine, evasion framework, and more.
*   A complete, auto-generated **API Reference** for the entire codebase.

## 🤝 Contributing

Contributions are welcome! We are excited to build a community around this project.

Please read our **[Contribution Workflow Guide](packages/auto_apply/docs/03_developer_guide/01_contribution_workflow.md)** to learn how you can report bugs, suggest features, or submit code changes.

## 📄 License

This project is licensed under the MIT License - see the `LICENSE` file for details.

[python-badge]: https://img.shields.io/badge/python-3.9+-blue.svg
[python-link]: https://www.python.org/downloads/
[license-badge]: https://img.shields.io/badge/license-MIT-green.svg
[license-link]: https://github.com/Liebmann5/AA/blob/main/LICENSE
[black-badge]: https://img.shields.io/badge/code%20style-black-000000.svg
[black-link]: https://github.com/psf/black
[docs-badge]: https://img.shields.io/badge/docs-mkdocs-blue.svg
[docs-link]: https://github.com/Liebmann5/AA/tree/main/packages/auto_apply/docs
