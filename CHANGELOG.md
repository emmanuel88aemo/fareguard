# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Project standards: typed package skeleton, ruff, mypy --strict, pytest, pre-commit and CI.
- Conventional Commits check for commit subjects.
- Contributing guide, decision records and security policy.
- Pure decision logic for the spend gate: typed models, started-minute pricing and an
  `evaluate` function that allows or denies a tool call against rules R1 to R5. Every denial
  names its rule; R5 denies a call that is malformed or cannot be evaluated. Disc ids and
  approval refs have a strict shape, and a denial reason never repeats other text from the call.
- Ledger store contract and an in-memory implementation: a launch consumes its approval,
  adds to the disc and monthly spend and writes its event atomically, or changes nothing.
