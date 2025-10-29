# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- Introduced PlaywrightAdapter abstraction for job application navigation.
- Added offline CAPTCHA solving via Vosk + SpeechRecognition.
- Initial monorepo structure with `auto_apply` as primary package.
- Modular design for evasion, scraping, and UI components.
- Initial developer and user documentation.
- Virtual environment setup scripts (`run.sh`, `run.bat`).

### Changed
- Refactored core factories into modular subpackages.
- Improved dependency management using `pyproject.toml`.

### Fixed
- Resolved issue with Chrome fingerprint detection.

## [0.1.0] - 2025-10-20
### Added
- Initial public release.
- AutoApply currently utilizes Setuptools to run.



NOTE: You can automate version bumps using commitizen or cz-cli later for CI/CD integration