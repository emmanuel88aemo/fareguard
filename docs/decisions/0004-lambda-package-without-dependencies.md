# 0004. Lambda package without dependencies

- Status: Accepted
- Date: 2026-11-25

## Context

The two Lambda functions run the code in `src/fareguard`. Its only third-party import is
`boto3`, and the Python runtime of Lambda already contains `boto3` and `botocore`.

## Decision

The deployment package is one zip of `src/`, built by Terraform with the `archive` provider.
It holds the `fareguard` package and nothing else. `boto3` is not bundled: the functions use
the one in the runtime.

## Alternatives considered

- **Bundle `boto3` in the zip.** The version would be pinned and identical to the tested one,
  but the build would need `pip`, a build step outside Terraform and a package of several
  megabytes for calls that every recent `boto3` supports.
- **A Lambda layer with the dependencies.** The same build step, plus one more resource, for
  a single dependency.

## Consequences

- Building needs only Terraform: no `pip`, no Docker and no script.
- AWS chooses the version of `boto3` and changes it when it updates the runtime. The tests run
  against the version installed locally, not that one. The code must keep to DynamoDB calls
  that have been stable for a long time (`Query`, `GetItem`, `TransactWriteItems`).
- A second third-party dependency, or the need for a feature newer than the runtime's
  `boto3`, reopens this decision: the package then needs a real build step.
