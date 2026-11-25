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
- DynamoDB ledger store: one table, with each launch and each approval request written as a
  single transaction of conditional writes.
- Opt-in tests of the DynamoDB ledger store against real DynamoDB, selected by the `aws` marker
  and skipped unless `FAREGUARD_RUN_AWS_TESTS=1`. The suite was run against real DynamoDB:
  67 of 68 tests passed, including the concurrent launches and the order in which failed
  conditions are reported. The one failure showed that DynamoDB drops the trailing zeros of a
  number, so an amount written as 0.20 was read back as 0.2; moto keeps them and had hidden it.

### Fixed

- Every store returns an amount of USD in whole cents with two decimal places. A stored amount
  that is negative, not finite or not a whole number of cents is a `LedgerDataError`; it is
  never rounded.
