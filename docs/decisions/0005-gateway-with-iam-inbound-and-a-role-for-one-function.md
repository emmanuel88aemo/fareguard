# 0005. Gateway with IAM inbound authorisation and a role for one function

- Status: Accepted
- Date: 2026-11-25

## Context

The harness reaches the four tools through an AgentCore Gateway, which invokes the tools
Lambda. Two things have to be chosen: who may call the gateway, and what the gateway may do
with the role it assumes.

## Decision

The gateway authorises its callers with IAM (`AWS_IAM`), and its role may invoke the tools
function and do nothing else. The only caller is the harness, which runs in the same account
under a role of its own, so IAM already knows it: a call is signed with that role's
credentials and allowed by `bedrock-agentcore:InvokeGateway` on this gateway, and there is
no identity provider to run, no client secret to keep and no token for the model to see or
repeat. The gateway's role is the identity under which a tool call leaves the gateway, so it
is held to the one thing a tool call needs: `lambda:InvokeFunction` on the tools function,
by its exact ARN. It is trusted by `bedrock-agentcore.amazonaws.com` only, for resources of
this account only, and Terraform owns its complete list of policies, as it does for the two
Lambda roles (record 0003). Whatever is added to the gateway later, by hand or by mistake,
cannot reach the hook function, the ledger table or any other resource through this role.

## Alternatives considered

- **A JWT authoriser (`CUSTOM_JWT`).** It needs an identity provider, a client and a secret,
  for a caller that already has an IAM role.
- **`AUTHENTICATE_ONLY` or `NONE`.** The gateway would then authorise nobody: any signed
  caller, or any caller at all, would reach the tools.
- **A resource policy on the function.** The gateway and the function are in the same
  account, where the policy of the role is enough. A second grant would be a second place
  to keep right.
- **A wildcard on the functions of the project.** Shorter, but the gateway could then invoke
  the hook function, which no tool call needs.

## Consequences

- No role may call the gateway yet. The role of the harness needs
  `bedrock-agentcore:InvokeGateway` on this gateway, in the pull request that creates it.
- A second Lambda target needs its function added to the policy of the role in the same pull
  request, or its calls fail in AWS with `AccessDenied` although `terraform validate` passes.
- The trust policy names the account, not the gateway: any AgentCore resource of this
  account that is given this role could assume it. What it could do with it is still one
  `InvokeFunction`.
- A target in another account would need a resource policy on its function as well.
