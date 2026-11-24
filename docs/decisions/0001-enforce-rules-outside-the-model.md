# 0001. Enforce rules outside the model

- Status: Accepted
- Date: 2026-11-24

## Context

Fareguard operates a job queue where every launched job costs money. Its rules (spend caps,
human approval, no access to secrets) must hold even when a prompt persuades the model to
break them. Instructions in a system prompt are a request to the model, not a control.

## Decision

Every rule is enforced by a mechanism the model cannot reach or edit:

- The tool surface is a closed allowlist. Tools that would break a rule do not exist.
- A Lambda hook evaluates each proposed tool call and denies it when a cap or an approval
  check fails. The hook fails closed.
- IAM limits what the agent's role and the tools' role can do.
- Approval is recorded by a person through a channel the agent has no tool for.

The system prompt describes the rules so the agent behaves well. It is never the enforcement.

## Alternatives considered

- **Prompt-only rules.** Simple, but a single successful injection defeats them.
- **A second model as judge.** Adds cost and latency, and the judge can be persuaded too.

## Consequences

- Each rule must name its mechanism, and each mechanism needs a test.
- Stress results are decided by code that reads the session record, not by the model's reply.
- More moving parts than a prompt: a hook, roles and a ledger must be deployed and kept in sync.
