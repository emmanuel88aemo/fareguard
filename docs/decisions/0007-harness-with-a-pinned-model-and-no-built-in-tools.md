# 0007. Harness with a pinned model and no built-in tools

- Status: Accepted
- Date: 2026-11-25

## Context

The AgentCore harness runs the agent loop: it calls the model, offers it tools and invokes
the hook. A harness that is created with only a name and a role fills in everything else
from managed defaults, and its documentation says these defaults can change:

- **The model.** Without `model`, the harness uses "the current AgentCore recommended
  model", a larger and dearer model than this agent needs, and one the execution role would
  have to be allowed to invoke.
- **The tools.** Without `allowedTools`, or with `["*"]`, the model is offered "the current
  recommended built-in tool set": `shell`, `read`, `write`, `edit`, `todo_write`,
  `retrieve_context`, `subagent` and `web_fetch`, and whatever is added to the set later.
- **The memory.** Managed memory is enabled by default: the harness creates a Memory
  resource in the account and the execution role needs permissions on it.

The agent is a dispatcher with four tools behind one gateway. It has no use for a shell, for
files, for the web or for memory across sessions.

`InvokeHarness` accepts, per call, a `model`, a `systemPrompt`, `tools`, `allowedTools`,
`maxIterations`, `maxTokens` and `timeoutSeconds` that replace those of the harness for that
call. Hooks are the exception: they are set by `CreateHarness` and `UpdateHarness` only.

## Decision

**The harness configuration states every setting that matters and relies on no default.**
It is built by one pure, tested function, `fareguard.harness.config.build_harness_config`.

- **The model is pinned** to the Amazon Nova 2 Lite inference profile,
  `us.amazon.nova-2-lite-v1:0`. The function refuses any other model id, and the execution
  role may invoke this model and no other.
- **The gateway is the only tool source.** `tools` holds one entry, of type
  `agentcore_gateway`, named `fareguard`, signed with the execution role (`awsIam`).
- **`allowedTools` lists exactly four selectors,** `@fareguard/fareguard___<tool>` for
  `read_ledger`, `list_pending`, `request_approval` and `launch_job`. A plain name in
  `allowedTools` selects a built-in tool and `@<name>/<tool>` selects a configured one, so a
  list that holds only these four enables no built-in tool, now or when the recommended set
  grows.
- **Memory is disabled** explicitly, with `memory: {"disabled": {}}`.
- **The hook is registered three times,** for `before_invocation`, `before_tool_call` and
  `after_tool_call`, each with `failureMode` `deny` (record 0006).
- **The limits are stated:** iterations, output tokens and seconds per invocation.

**The configuration is a default, not a security boundary.** Whoever may call
`InvokeHarness` on this harness can replace the model, the system prompt, the tools, the
allowed tools and the limits for one call. Only the hooks cannot be overridden. Enforcement
therefore rests on two things the caller cannot change:

- **The hooks.** Every invocation and every tool call goes to the hook function, and a hook
  that fails, times out or answers badly denies. A tool that a caller adds to a call, built
  in or not, is denied with R1 by `before_tool_call`, because it is not one of the four.
- **IAM.** The execution role may invoke one model, one gateway and one function. A call
  that names another Bedrock model is refused by Bedrock.

The model is pinned in the configuration all the same: it is the sane default, it is what a
call without overrides uses, and it keeps the cost of a run known.

## Alternatives considered

- **Leave the model to the service default.** The model, its price and its behaviour would
  change without a change in this repository, and the role would need a wider grant.
- **`allowedTools: ["*"]` and rely on the hook.** The hook would deny every built-in call
  with R1, but the model would be offered about 3,000 tokens of tool definitions on every
  request and would spend iterations on calls that are always refused.
- **`allowedTools: ["@fareguard"]`,** every tool of the gateway. A tool added to the gateway
  later would be offered to the model without a change here.
- **Managed memory.** It would carry text from one session into the next, past the
  `before_invocation` screen, and needs a resource and permissions the agent does not use.

## Consequences

- **A caller of `InvokeHarness` is trusted with the model's cost and instructions, not with
  the rules.** `bedrock-agentcore:InvokeHarness` on this harness must be granted narrowly. A
  caller can replace the system prompt; it cannot make a launch pass the gate.
- **A caller can make the agent loop longer** by raising the limits per call. The spend
  rules are unaffected; the token cost of that call is not.
- **A tool the hook does not screen cannot be added by a caller without being denied,** but
  a remote MCP server named in a call is still contacted by the harness when it lists that
  server's tools. The execution role has no permission that such a server could use.
- The tool names in `allowedTools` contain the gateway target name. Renaming the target in
  `infra/main/gateway.tf` needs the same change in `fareguard.harness.config`.
- Whether a harness accepts Amazon Nova 2 Lite is not confirmed: the documentation shows
  another Nova model only. If the first invocation is rejected, the model is changed by a
  new record, in the configuration and in the role together.
- The harness is created by a script a person runs, not by Terraform, so it is not in the
  state: deleting it is a manual step, documented in `harness/README.md`.
