# fareguard

Fareguard is a spend-gated agent that dispatches paid GPU jobs. It reads a ledger, asks a
person to approve each launch, and may launch only with that approval and within a cap per
disc and a monthly cap. In this repository the launch is simulated: the ledger record is the
job.

The model is never trusted to enforce a rule: code and IAM are. A hook allows or denies each
tool call, the ledger records a launch in one atomic write, and the agent has no tool that
approves.

- [Architecture](docs/architecture.md): the rules R1 to R7, how each is enforced, a diagram,
  the stress results and the failures that were fixed.
- [Stress cases](docs/stress/cases.md) and [results](docs/stress/results.md).
- [Decision records](docs/decisions/README.md).
- [Infrastructure](infra/README.md) and [harness](harness/README.md): how a person deploys
  and runs it.
- [Contributing](CONTRIBUTING.md) and [security](SECURITY.md).
