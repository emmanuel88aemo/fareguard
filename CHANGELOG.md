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
- Hook decision logic for the AgentCore harness: `decide` answers a `before_tool_call` event
  with allow or deny from the gate's outcome and returns a record for logging. Any other event
  type and a missing, truncated or malformed tool input are denied with R5, as is a call whose
  evaluation fails. A tool name may carry a gateway target prefix, `<target>___<tool>`; that
  format is an assumption to confirm at deploy time.
- The reason returned by the hook is a fixed sentence per rule that starts with the rule id.
  It contains no text from the event, so it is shorter than the gate's own reason: it names
  no disc, approval or amount.
- The hook's log record keeps what the agent no longer sees: `detail`, the gate's own reason,
  and `raw_tool`, the tool name as it arrived, cut to 128 characters. Neither is returned to
  the harness. `detail` may quote a disc id or an approval ref that has the strict shape of an
  identifier; no other argument text is logged.
- Lambda configuration from the environment variables `FAREGUARD_TABLE_NAME`,
  `FAREGUARD_MAX_USD_PER_DISC`, `FAREGUARD_MONTHLY_CAP_USD` and `FAREGUARD_USD_PER_MINUTE`.
  All are required and none has a default.
- Hook Lambda handler: it builds the DynamoDB client, the store and the limits once per
  container, logs one JSON line per decision and denies with R5 on any error, including a
  missing or invalid environment variable. It is not deployed: no Terraform exists yet.

### Fixed

- Every store returns an amount of USD in whole cents with two decimal places. A stored amount
  that is negative, not finite or not a whole number of cents is a `LedgerDataError`; it is
  never rounded.
