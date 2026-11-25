# 0006. Guardrail applied by the hook, as a second layer

- Status: Accepted
- Date: 2026-11-25

## Context

Record 0001 puts every rule outside the model: the gate, the tools and IAM hold even when
the model has been persuaded to break them. That leaves the persuasion itself untouched.
Text reaches the model from two places nobody on the project writes: what a caller sends,
and what a tool returns. `read_ledger` returns ledger events under `untrusted_ledger_events`
because nothing constrains what an event holds, so an instruction planted in the ledger
arrives in a tool result (stress case A2).

A Bedrock Guardrail can screen text for prompt attacks and for denied topics. Two things
have to be chosen: where it is applied, and what may depend on it.

The harness invokes a hook on four events. Its documentation says that a Lambda `deny`
stops the invocation before the agent starts on `before_invocation`, and on
`after_tool_call` keeps the completed tool result and then stops the invocation.

## Decision

**The hook function calls `ApplyGuardrail` itself. The guardrail is not attached to the
harness or to a model.**

- The hook answers two more events. On `before_invocation` it sends the text of the messages
  of the request, and on `after_tool_call` every text of the tool result and of its error.
  Both go to the guardrail with the source `INPUT`.
- Text the guardrail blocks is denied under a new rule, **R7**, with one fixed sentence. The
  blocked text is neither returned nor logged, and the guardrail's own blocked message is
  not passed on.
- Whatever keeps the whole text from being checked is denied under R5: a context that is
  missing, marked as truncated or not shaped as documented, a message block that is not
  text, a guardrail call that fails, is throttled or times out, a response that does not
  say every character was guarded, and an event name the hook does not know.
- The guardrail has one content filter, prompt attacks at `HIGH` on input, and one denied
  topic: asking the agent to change, lift or ignore its spending limits or approval rules.
- The hook applies a published version by its number, never the working draft.

**The guardrail is a second layer. No rule depends on it alone.** A launch is still judged
by the gate in the hook (R1 to R5) and again by the tools and the ledger store (R2 to R6),
from the ledger and the limits, not from anything the model was told. An injection the
guardrail misses can change what the model asks for; it cannot change what is allowed. A
test holds this: a launch over the cap is denied with R2 after the guardrail let the
injection through.

### Why from the hook

- **Tool results are where the planted text arrives, and a guardrail attached to inference
  does not screen them for prompt attacks.** The Bedrock documentation states that the
  prompt attack filter does not evaluate `messages[].content[].toolResult`. Called through
  `ApplyGuardrail` with the source `INPUT`, the same filter judges exactly that text.
- **The failure behaviour is ours.** The hook decides what happens when the guardrail
  cannot answer, when the context is truncated and when the coverage is partial: it denies.
- **One decision point, one log, one vocabulary.** A block is a rule id with a fixed
  sentence and a log record, like every other denial, and is tested without AWS behind a
  port (`Guardrail`) with a fake.
- **The permission is narrow.** Only the hook role may call `bedrock:ApplyGuardrail`, on
  this guardrail only.

## Alternatives considered

- **Attach the guardrail to the model calls of the harness.** Whether the harness can do
  that was not examined. Even if it can, the prompt attack filter would skip tool results,
  and a block would surface as a model response instead of a denial with a rule.
- **Only the system prompt and the `untrusted_ledger_events` key.** Both stay, and both are
  requests to the model (record 0001).
- **Remove blocked text from the tool result.** The hook cannot: `after_tool_call` may
  allow or deny, not rewrite.
- **Rely on the guardrail to stop launches.** A classifier misses. The spend rules do not
  consult it.

## Consequences

- **A denied tool result stays in the session.** The harness keeps the result and stops the
  invocation; the `before_invocation` context of a later request does not include messages
  restored from session state. R7 on `after_tool_call` therefore ends the run, not the
  exposure: a session that was stopped this way should not be continued. This is the main
  reason no rule may depend on the guardrail.
- **Cost.** Guardrails are billed per text unit of up to 1,000 characters, per policy: 0.15
  USD per 1,000 text units for content filters and the same for denied topics (Bedrock
  pricing page, read on 2026-11-25). This guardrail has both, so a call costs 0.0003 USD
  per started 1,000 characters. The harness limits a hook context to 64 KiB, so one call
  costs at most about 0.02 USD. There is one call per invocation and one per tool result
  that holds text; an event without text makes no call.
- **Latency and availability.** Each of those events waits for one API call. The client
  makes one attempt, with 2 seconds to connect and 6 to read, inside the function's 10
  seconds. While Bedrock is unavailable or throttling, invocations and tool results are
  denied with R5; tool calls are still decided, because `before_tool_call` does not use
  the guardrail.
- **Large or non-text content is denied.** A request or a tool result whose context
  exceeds 64 KiB is truncated by the harness and denied with R5, and so is a message that
  holds an image or a document. `read_ledger` must keep its result under that size.
- **False positives are possible,** for example a caller who asks what the monthly cap is.
  The topic and the strength are tuned in `infra/main/guardrail.tf`; every change publishes
  a new version and gives its number to the hook.
- **The harness must keep `failureMode` at `deny`** for the hook, in the pull request that
  creates it, and register the hook for `before_invocation`, `before_tool_call` and
  `after_tool_call`.
- The hook's `boto3` call goes beyond the DynamoDB calls named in record 0004:
  `apply_guardrail` must exist in the `boto3` of the Lambda runtime. It has not been called
  in AWS yet.
