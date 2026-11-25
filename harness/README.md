# Harness

The AgentCore harness runs the agent: it calls the model, offers it the four tools of the
gateway and invokes the hook function on every invocation and every tool call. Why it is
configured as it is, and what the configuration does not protect, is in
[decision record 0007](../docs/decisions/0007-harness-with-a-pinned-model-and-no-built-in-tools.md).

**A person creates and invokes the harness, with the two scripts below.** No workflow and no
AI assistant runs them. Terraform does not create the harness, so it is not in the state.

| File | What it is |
|---|---|
| `harness/system_prompt.md` | The instructions of the agent, sent as they are |
| `src/fareguard/harness/config.py` | The pure function that builds the arguments of `CreateHarness` |
| `src/fareguard/harness/stream.py` | Reads the response stream of `InvokeHarness` into a transcript |
| `scripts/create_harness.py` | Creates the harness |
| `scripts/invoke_harness.py` | Sends one message to the harness and prints what happened |

## What the harness is created with

| Setting | Value |
|---|---|
| Name | `fareguard_<env>`; a harness name allows no hyphen |
| Model | `us.amazon.nova-2-lite-v1:0`, the Amazon Nova 2 Lite inference profile; no other is accepted by the function or allowed by the role |
| Tools | one entry of type `agentcore_gateway`, named `fareguard`, signed with the execution role |
| Allowed tools | `@fareguard/fareguard___read_ledger`, `@fareguard/fareguard___list_pending`, `@fareguard/fareguard___request_approval`, `@fareguard/fareguard___launch_job` |
| Built-in tools | none: no `shell`, `read`, `write`, `edit`, `todo_write`, `retrieve_context`, `subagent` or `web_fetch`, because no selector names one |
| Memory | disabled |
| Hooks | the hook function on `before_invocation`, `before_tool_call` and `after_tool_call`, each with `failureMode` `deny` and a wait of 15 seconds |
| Limits per invocation | 12 iterations, 4,096 output tokens, 300 seconds |

The limits are constants of `scripts/create_harness.py`.

This is a default, not a boundary. A caller of `InvokeHarness` can replace the model, the
system prompt, the tools, the allowed tools and the limits for one call; only the hooks
cannot be overridden. The rules hold through the hooks and through the execution role.
`scripts/invoke_harness.py` overrides nothing.

## Before you start

- `infra/main` is applied, including the execution role of the harness; see
  [`infra/README.md`](../infra/README.md). `terraform output` must work in `infra/main`.
- The package is installed: `pip install -e ".[dev]"`.
- AWS credentials from the default chain. Besides reading the Terraform state, they need:

| To | Actions |
|---|---|
| create | `bedrock-agentcore:CreateHarness`, `bedrock-agentcore:CreateAgentRuntime`, and `iam:PassRole` on the execution role |
| invoke | `bedrock-agentcore:InvokeHarness` and `bedrock-agentcore:InvokeAgentRuntime` on the harness |
| delete | `bedrock-agentcore:DeleteHarness`, `bedrock-agentcore:DeleteAgentRuntime` |

  The AgentCore documentation also lists `bedrock-agentcore:CreateMemory` for
  `CreateHarness`. Whether it is needed when memory is disabled has not been tested, and
  `iam:PassRole` is not named there at all: both are to confirm on the first run.

## Create

Look at the configuration first. This reads the Terraform outputs and calls no other API:

```bash
python scripts/create_harness.py --dry-run
```

It prints ARNs of your account: do not paste the output into an issue or a commit.

Then create the harness. This calls `CreateHarness` once:

```bash
python scripts/create_harness.py
```

It prints the ARN and the status of the harness. The harness is ready when its status is
`READY`; `aws bedrock-agentcore-control get-harness --harness-id <id>` shows it, where the
id is the last part of the ARN. Running the script a second time fails, because the name is
taken: delete the harness first, or change it with `update-harness`.

## Invoke

```bash
export FAREGUARD_HARNESS_ARN=<the ARN the create script printed>
python scripts/invoke_harness.py "What is queued, and what is waiting for approval?"
```

The script generates a runtime session id of 42 characters (the API requires 33 to 100) and
prints it first. To continue the same session, pass it back:

```bash
python scripts/invoke_harness.py --session-id <that id> "Ask for approval for disc d1."
```

It then prints the model's reply, each tool call with its input, what each hook decided and
its reason, and why each message stopped. `--dry-run` prints the request and calls nothing.

The script makes one attempt and never retries, so a message is not sent twice. It exits
with 1 when the call or the stream reported an error.

A session that a hook stopped (`hook_stopped`) should not be continued: start a new one.
The denied tool result stays in the session, as record 0006 explains.

## Not confirmed yet

**Whether a harness accepts Amazon Nova 2 Lite.** The AgentCore documentation names no list
of supported models and shows only another Nova model, `us.amazon.nova-micro-v1:0`, in an
example. Nothing here has been run against AWS.

If the model is rejected, `scripts/invoke_harness.py` prints the error exactly as AWS
returned it: a `runtimeClientError` or `validationException` event of the stream after
`error:`, or the full error response of the API on standard error. Keep that text. The
model is then changed by a new decision record, in `fareguard.harness.config` and in
`infra/main/iam_harness.tf` together; neither script falls back to another model.

Also to confirm on the first run:

- which statements of the execution role a harness fails without;
- that the hook receives gateway tool names as `fareguard___<tool>`, as a direct call to
  the gateway showed;
- that Amazon Nova 2 Lite is enabled for the account in the regions of the US profile.

## Delete

```bash
aws bedrock-agentcore-control delete-harness --harness-id <id>
```

Delete the harness before `infra/main` is destroyed. Its log group,
`/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`, was created by AgentCore and has to
be deleted by hand; that name follows the pattern of AgentCore Runtime and is to confirm.
