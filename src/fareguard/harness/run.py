"""Send one message to the harness and return what happened as one typed result.

The caller passes the bedrock-agentcore client and the ARN of the harness, so a
test passes a fake and nothing here reads the environment. Nothing of the
harness is overridden: the call uses the model, the prompt, the tools and the
limits it was created with.
"""

import re
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from fareguard.harness.stream import (
    HookDecision,
    ToolCall,
    Transcript,
    format_transcript,
    read_stream,
)

# InvokeHarness requires a runtime session id of 33 to 100 characters.
SESSION_ID = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{32,99}$")
# A denial reason of the hook starts with the rule that denied, as in "R4: ...".
_RULE = re.compile(r"^(R\d+):")

# One attempt: a retry would send the message, and perhaps a launch, a second time.
# The read timeout is longer than the 300 seconds an invocation may take.
CLIENT_CONFIG = Config(read_timeout=330, retries={"total_max_attempts": 1})


class RuntimeClient(Protocol):
    """The one operation of the bedrock-agentcore client that is used."""

    def invoke_harness(self, **kwargs: object) -> Mapping[str, object]:
        """Invoke a harness and return the response of the API, which holds the stream."""


class InvalidRequestError(ValueError):
    """The request cannot be sent: the ARN, the session id or the message is not usable."""


@dataclass(frozen=True)
class HookVerdict:
    """What one hook answered.

    `decision` is "allow" or "deny" as the hook gave it, or None for a target
    that returns none. `rule` is the rule a reason names, such as "R4", or None
    when the reason names no rule, as an allow does.
    """

    event: str
    name: str
    decision: str | None
    rule: str | None
    reason: str | None


@dataclass(frozen=True)
class HarnessRun:
    """Everything one invocation produced, in the order it arrived.

    `errors` are the error events of the stream, word for word. `failure` is the
    error the call or the stream raised, or None; what arrived before it is kept.
    """

    session_id: str
    reply: str
    tool_calls: tuple[ToolCall, ...]
    hook_decisions: tuple[HookVerdict, ...]
    stop_reasons: tuple[str, ...]
    errors: tuple[str, ...]
    failure: ClientError | BotoCoreError | None

    @property
    def ok(self) -> bool:
        """Whether the call completed and its stream carried no error event."""
        return self.failure is None and not self.errors


def new_session_id() -> str:
    """Return a new runtime session id: 42 characters, within the 33 to 100 required."""
    return f"fareguard-{uuid.uuid4().hex}"


def build_request(harness_arn: str, session_id: str, message: str) -> dict[str, object]:
    """Return the arguments of InvokeHarness for one user message, with no override.

    Raises:
        InvalidRequestError: the ARN or the message is empty, or the session id
            is not 33 to 100 letters, digits, - or _.
    """
    problem = _problem(harness_arn, session_id, message)
    if problem is not None:
        raise InvalidRequestError(problem)
    return {
        "harnessArn": harness_arn,
        "runtimeSessionId": session_id,
        "messages": [{"role": "user", "content": [{"text": message}]}],
    }


def run_harness(
    client: RuntimeClient, harness_arn: str, message: str, session_id: str | None = None
) -> HarnessRun:
    """Call InvokeHarness once with `message` and return what its stream held.

    A new runtime session id is generated when `session_id` is None. An error of
    the API or of the connection is not raised: it is returned as `failure`,
    with what arrived before it.

    Raises:
        InvalidRequestError: the request cannot be built; nothing was called.
    """
    session = new_session_id() if session_id is None else session_id
    request = build_request(harness_arn, session, message)
    events: list[object] = []
    failure: ClientError | BotoCoreError | None = None
    try:
        stream = client.invoke_harness(**request).get("stream")
        events.extend(stream if isinstance(stream, Iterable) else ())
    except (ClientError, BotoCoreError) as error:
        failure = error
    transcript = read_stream(events)
    return HarnessRun(
        session_id=session,
        reply=transcript.reply,
        tool_calls=transcript.tool_calls,
        hook_decisions=tuple(_verdict(hook) for hook in transcript.hook_decisions),
        stop_reasons=transcript.stop_reasons,
        errors=transcript.errors,
        failure=failure,
    )


def format_run(run: HarnessRun) -> str:
    """Return the run as lines of text: reply, tool calls, hooks, stops and errors."""
    return format_transcript(
        Transcript(
            reply=run.reply,
            tool_calls=run.tool_calls,
            hook_decisions=tuple(
                HookDecision(hook.name, hook.event, hook.decision, hook.reason)
                for hook in run.hook_decisions
            ),
            stop_reasons=run.stop_reasons,
            errors=run.errors,
        )
    )


def _problem(harness_arn: str, session_id: str, message: str) -> str | None:
    """Return what is wrong with the request, or None when it can be sent."""
    if not harness_arn.strip():
        return "the harness ARN must not be empty"
    if not message.strip():
        return "the message must not be empty"
    if SESSION_ID.fullmatch(session_id) is None:
        return "the session id must be 33 to 100 letters, digits, - or _"
    return None


def _verdict(hook: HookDecision) -> HookVerdict:
    named = _RULE.match(hook.reason or "")
    return HookVerdict(
        event=hook.event,
        name=hook.name,
        decision=hook.decision,
        rule=named.group(1) if named else None,
        reason=hook.reason,
    )
