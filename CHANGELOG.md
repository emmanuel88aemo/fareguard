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
- The agent's tools as pure logic in `fareguard.tools`: `read_ledger`, `list_pending`,
  `request_approval` and `launch_job`, and `dispatch`, which routes a call to one of them.
  Amounts are strings with two decimals. `launch_job` does not rely on the hook: it takes its
  own snapshot, asks the gate again and only then records the launch, which the store checks
  once more atomically. The launch is simulated: the ledger record is the job.
- `request_approval` estimates the cost from the disc's duration and takes its ref from an
  injected factory.
- Rule R6: a disc has at most one pending approval request. The ledger store holds it in its
  atomic write and `request_approval` reports it; the gate does not evaluate it. A generated
  ref that is already taken is refused with R5. Every refusal of every tool names a rule.
- A tool result never repeats text from the call, not even a disc id or an approval ref with
  a valid shape. A refusal carries the same fixed sentence per rule as the hook; an unknown
  tool is R1, and a missing tool name or malformed arguments are R5. The gate's and the
  store's own reasons are kept beside the result as `detail`, for the log only.
- `read_ledger` returns events under the key `untrusted_ledger_events`, because nothing
  constrains what an event holds. A ledger whose disc, approval or amount is malformed is
  refused with R5 instead of shown.
- Tools Lambda handler: it reads the tool name from
  `context.client_context.custom["bedrockAgentCoreToolName"]`, removes a gateway target prefix
  with the hook's normalisation and treats the event as the tool's arguments. Both are
  assumptions to confirm at deploy time. It logs one JSON line per call and answers any error,
  including a missing or invalid environment variable, with a refusal under R5. It is not
  deployed: no Terraform exists yet.
- Terraform base in `infra/`, described in `infra/README.md` and decision record 0003.
  `infra/bootstrap` creates the S3 bucket for the state; `infra/main` keeps its state there,
  locked with the S3 lock file, and creates the ledger table, a log group per Lambda with 14
  days of retention and a role per Lambda. No function, gateway, guardrail or harness exists
  yet. It passes `terraform validate` only: nothing has been planned or applied in AWS.
- The role of the hook Lambda may query and get items of the ledger table and write to its
  own log group. The role of the tools Lambda may also put items whose partition key is
  `APPROVAL` or `EVENT` and update items whose partition key is `DISC`, `APPROVAL` or `SPEND`.
  It cannot delete an item or update an event, whatever the code does.
- CI job that checks `terraform fmt` and runs `terraform validate` in both directories,
  without AWS credentials.
- Terraform for the two Lambda functions, `fareguard-<env>-hook` and `fareguard-<env>-tools`,
  with their environment variables; the three limits are Terraform variables. Both run one
  zip that Terraform builds from `src/` with no dependency in it: `boto3` comes from the
  runtime (decision record 0004). It passes `terraform validate` only: the functions have
  not been planned, applied or invoked in AWS.
- Terraform for the AgentCore Gateway `fareguard-<env>-gateway`: MCP, with inbound
  authorisation by IAM, and one Lambda target named `fareguard` that declares the four tools
  with their arguments, so a caller sees them as `fareguard___<tool>`. The role of the
  gateway may invoke the tools function and nothing else (decision record 0005). The
  function needs no resource policy, because the gateway is in the same account. The target
  is created 20 seconds after the role of the gateway, because a first apply failed while
  AgentCore could not yet assume a role that IAM had just created. The gateway was applied
  and called in AWS: the tools are listed and called as `fareguard___<tool>`, with three
  underscores, which confirms the prefix the hook and the tools handler remove.
- Rule R7: text blocked by the content guardrail. The hook reports it with one fixed
  sentence; the gate and the tools do not evaluate it.
- A port for the guardrail in `fareguard.hook`: the `Guardrail` protocol, `BedrockGuardrail`,
  which calls `ApplyGuardrail` with the source `INPUT`, and `FakeGuardrail` for tests. The
  Bedrock implementation raises unless the response names a known action and states that
  every character was guarded. Its client makes one attempt of at most 8 seconds.
- The hook answers two more events through `screen`: `before_invocation`, with the text of
  the request's messages, and `after_tool_call`, with every text of the tool result and its
  error. Text the guardrail blocks is denied with R7. A context that is missing, truncated
  or not shaped as documented, a message block that is not text, a guardrail that fails or
  times out and an event name the hook does not know are denied with R5. The log record
  names the event and a fixed reason, and never the text. `before_tool_call` is decided as
  before, without the guardrail.
- Hook configuration from `FAREGUARD_GUARDRAIL_ID` and `FAREGUARD_GUARDRAIL_VERSION`, both
  required, with no default; the version must be a published number. The hook reads them
  when the first text has to be screened, and the tools function does not read them.
- Terraform for the Bedrock Guardrail `fareguard-<env>-guardrail` and one published version:
  the prompt attack filter at `HIGH` on input and one denied topic, asking the agent to
  change, lift or ignore its spending limits or approval rules. The hook role may call
  `bedrock:ApplyGuardrail` on this guardrail only, and the hook function receives its id and
  version (decision record 0006). The guardrail is a second layer: no rule depends on it.
  It passes `terraform validate` only: the guardrail has not been planned, applied or
  called in AWS, and no harness invokes the hook yet.
- Decision record 0007: the harness states its model, its tools, its memory, its hooks and
  its limits and relies on no default of the service. The configuration is a default, not a
  security boundary: `InvokeHarness` can replace the model, the system prompt, the tools,
  the allowed tools and the limits per call, and only the hooks cannot be overridden. The
  rules rest on the hooks and on IAM.
- Terraform for the execution role of the harness, `fareguard-<env>-harness`, trusted by
  AgentCore for this account only. It may invoke the hook function, the gateway and one
  model, Amazon Nova 2 Lite, and holds the minimum policy the AgentCore documentation gives
  for an execution role: the pull of the managed image, logs, traces, metrics and the
  workload identity. `infra/README.md` lists the statements that are wildcards and why. New
  outputs: `harness_name` and `harness_execution_role_arn`. It passes `terraform validate`
  only: the role has not been planned or applied in AWS.
- `fareguard.harness.config.build_harness_config`, a pure function that builds the arguments
  of `CreateHarness`. It pins the model to `us.amazon.nova-2-lite-v1:0` and refuses any
  other, offers the gateway as the only tool source, allows exactly the four selectors
  `@fareguard/fareguard___<tool>` and therefore no built-in tool, disables memory and
  registers the hook on `before_invocation`, `before_tool_call` and `after_tool_call` with
  `failureMode` `deny`. Its output is checked against the `CreateHarness` shape of `boto3`.
- `harness/system_prompt.md`, the instructions of the dispatcher: four tools, approval
  before launch, no attempt to change a limit or a rule, and tool output treated as data.
- `fareguard.harness.stream`, which reads the event stream of `InvokeHarness` into the
  reply, the tool calls, the hook decisions, the stop reasons and the errors, word for word.
- `scripts/create_harness.py` and `scripts/invoke_harness.py`, which a person runs; see
  `harness/README.md`. The first reads the ARNs from `terraform output`, the second sends
  one message under a runtime session id and prints an error exactly as AWS returned it.
  Both have `--dry-run`. Neither has been run: no harness exists yet, and whether a harness
  accepts Amazon Nova 2 Lite is not confirmed.

### Fixed

- Every store returns an amount of USD in whole cents with two decimal places. A stored amount
  that is negative, not finite or not a whole number of cents is a `LedgerDataError`; it is
  never rounded.
