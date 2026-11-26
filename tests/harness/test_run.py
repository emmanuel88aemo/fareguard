from collections.abc import Iterator, Mapping

import pytest
from botocore.exceptions import ClientError, ReadTimeoutError

from fareguard.harness.run import (
    CLIENT_CONFIG,
    SESSION_ID,
    HarnessRun,
    HookVerdict,
    InvalidRequestError,
    build_request,
    format_run,
    new_session_id,
    run_harness,
)
from fareguard.harness.stream import ToolCall

# A made-up value with the shape of a real ARN; the account is twelve zeros.
HARNESS_ARN = "arn:aws:bedrock-agentcore:us-east-1:000000000000:harness/fareguard_dev-abcdefghij"
SESSION = "session-0123456789012345678901234567890"
DENIAL = (
    "R4: the launch needs an approval that is approved, unused, issued for "
    "this disc and large enough"
)


class FakeRuntimeClient:
    """Answers invoke_harness with a fixed response, or raises a fixed error."""

    def __init__(
        self, response: Mapping[str, object] | None = None, error: Exception | None = None
    ) -> None:
        self.calls: list[dict[str, object]] = []
        self._response: Mapping[str, object] = {} if response is None else response
        self._error = error

    def invoke_harness(self, **kwargs: object) -> Mapping[str, object]:
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._response


def _hook(event: str, decision: str, reason: str) -> object:
    return {
        "hookEvent": {
            "hookEventId": "1234abcd-12ab-34cd-56ef-1234567890ab",
            "name": f"fareguard_{event}",
            "type": event,
            "decision": decision,
            "reason": reason,
        }
    }


def _text(text: str) -> object:
    return {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": text}}}


def _denied_launch() -> list[object]:
    """One turn in which the model calls launch_job, the hook denies it and the model says so."""
    tool_use = {"name": "fareguard___launch_job", "toolUseId": "t1"}
    return [
        _hook("before_invocation", "allow", "allowed"),
        {"messageStart": {"role": "assistant"}},
        {"contentBlockStart": {"contentBlockIndex": 0, "start": {"toolUse": tool_use}}},
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": '{"disc_id": "d1", '}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolUse": {"input": '"approval_ref": "a1"}'}},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "tool_use"}},
        _hook("before_tool_call", "deny", DENIAL),
        {"messageStart": {"role": "user"}},
        {
            "contentBlockStart": {
                "contentBlockIndex": 0,
                "start": {"toolResult": {"toolUseId": "t1", "status": "error"}},
            }
        },
        {
            "contentBlockDelta": {
                "contentBlockIndex": 0,
                "delta": {"toolResult": [{"text": DENIAL}]},
            }
        },
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"messageStart": {"role": "assistant"}},
        _text("The launch was denied: "),
        _text("it needs an approval."),
        {"contentBlockStop": {"contentBlockIndex": 0}},
        {"messageStop": {"stopReason": "end_turn"}},
        {"metadata": {"usage": {"inputTokens": 900, "outputTokens": 40}}},
    ]


def _stream_that_breaks(events: list[object], error: Exception) -> Iterator[object]:
    yield from events
    raise error


def test_a_generated_session_id_has_the_required_length() -> None:
    session_id = new_session_id()

    assert 33 <= len(session_id) <= 100
    assert SESSION_ID.fullmatch(session_id)
    assert session_id != new_session_id()


def test_the_client_configuration_never_sends_a_message_twice() -> None:
    # The stubs of botocore do not declare the attributes of Config.
    assert CLIENT_CONFIG.retries == {"total_max_attempts": 1}  # type: ignore[attr-defined]
    assert CLIENT_CONFIG.read_timeout > 300  # type: ignore[attr-defined]


def test_the_request_overrides_nothing_of_the_harness() -> None:
    assert build_request(HARNESS_ARN, SESSION, "hello") == {
        "harnessArn": HARNESS_ARN,
        "runtimeSessionId": SESSION,
        "messages": [{"role": "user", "content": [{"text": "hello"}]}],
    }


@pytest.mark.parametrize(
    ("harness_arn", "session_id", "message", "fragment"),
    [
        (" ", SESSION, "hello", "harness ARN"),
        (HARNESS_ARN, SESSION, "  ", "message"),
        (HARNESS_ARN, "short", "hello", "33 to 100"),
        (HARNESS_ARN, "x" * 101, "hello", "33 to 100"),
        (HARNESS_ARN, "-" + "x" * 40, "hello", "33 to 100"),
    ],
)
def test_a_request_that_cannot_be_sent_is_refused_before_any_call(
    harness_arn: str, session_id: str, message: str, fragment: str
) -> None:
    client = FakeRuntimeClient()

    with pytest.raises(InvalidRequestError, match=fragment):
        run_harness(client, harness_arn, message, session_id)

    assert client.calls == []


def test_a_denied_launch_is_read_into_one_result() -> None:
    client = FakeRuntimeClient({"stream": iter(_denied_launch())})

    run = run_harness(client, HARNESS_ARN, "Launch d1.", SESSION)

    assert client.calls == [build_request(HARNESS_ARN, SESSION, "Launch d1.")]
    assert run == HarnessRun(
        session_id=SESSION,
        reply="The launch was denied: it needs an approval.",
        tool_calls=(
            ToolCall("fareguard___launch_job", "t1", '{"disc_id": "d1", "approval_ref": "a1"}'),
        ),
        hook_decisions=(
            HookVerdict(
                "before_invocation", "fareguard_before_invocation", "allow", None, "allowed"
            ),
            HookVerdict("before_tool_call", "fareguard_before_tool_call", "deny", "R4", DENIAL),
        ),
        stop_reasons=("tool_use", "end_turn", "end_turn"),
        errors=(),
        failure=None,
    )
    assert run.ok


def test_a_hook_without_a_reason_names_no_rule() -> None:
    client = FakeRuntimeClient({"stream": [{"hookEvent": {"name": "notify", "type": "x"}}]})

    run = run_harness(client, HARNESS_ARN, "hello", SESSION)

    assert run.hook_decisions == (HookVerdict("x", "notify", None, None, None),)


def test_a_session_id_is_generated_when_none_is_given() -> None:
    client = FakeRuntimeClient({"stream": []})

    run = run_harness(client, HARNESS_ARN, "hello")

    assert SESSION_ID.fullmatch(run.session_id)
    assert client.calls[0]["runtimeSessionId"] == run.session_id


@pytest.mark.parametrize("response", [{"stream": []}, {}, {"stream": None}])
def test_an_empty_or_missing_stream_gives_an_empty_result(response: Mapping[str, object]) -> None:
    run = run_harness(FakeRuntimeClient(response), HARNESS_ARN, "hello", SESSION)

    assert run == HarnessRun(SESSION, "", (), (), (), (), None)
    assert run.ok


def test_an_error_event_of_the_stream_is_kept_and_the_run_is_not_ok() -> None:
    message = "The model us.amazon.nova-2-lite-v1:0 is not supported by this harness."
    client = FakeRuntimeClient({"stream": [{"runtimeClientError": {"message": message}}]})

    run = run_harness(client, HARNESS_ARN, "hello", SESSION)

    assert run.errors == (f'runtimeClientError: {{"message": "{message}"}}',)
    assert run.failure is None
    assert not run.ok


def test_an_error_of_the_api_is_returned_not_raised() -> None:
    error = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "not supported"}}, "InvokeHarness"
    )

    run = run_harness(FakeRuntimeClient(error=error), HARNESS_ARN, "hello", SESSION)

    assert run.failure is error
    assert run.reply == ""
    assert not run.ok


def test_what_arrived_before_the_stream_broke_is_kept() -> None:
    error = ReadTimeoutError(endpoint_url="https://example.invalid")
    events = _denied_launch()[:8]
    client = FakeRuntimeClient({"stream": _stream_that_breaks(events, error)})

    run = run_harness(client, HARNESS_ARN, "Launch d1.", SESSION)

    assert run.failure is error
    assert [call.name for call in run.tool_calls] == ["fareguard___launch_job"]
    assert [hook.rule for hook in run.hook_decisions] == [None, "R4"]
    assert run.stop_reasons == ("tool_use",)


def test_an_error_that_is_not_of_aws_is_raised() -> None:
    client = FakeRuntimeClient(error=RuntimeError("a bug, not an answer of AWS"))

    with pytest.raises(RuntimeError, match="a bug"):
        run_harness(client, HARNESS_ARN, "hello", SESSION)


def test_a_run_is_formatted_as_its_transcript() -> None:
    run = run_harness(
        FakeRuntimeClient({"stream": _denied_launch()}), HARNESS_ARN, "Launch d1.", SESSION
    )

    assert format_run(run) == "\n".join(
        [
            "reply:",
            "The launch was denied: it needs an approval.",
            "",
            "tool calls:",
            '  fareguard___launch_job {"disc_id": "d1", "approval_ref": "a1"}',
            "",
            "hook decisions:",
            "  before_invocation fareguard_before_invocation: allow (allowed)",
            f"  before_tool_call fareguard_before_tool_call: deny ({DENIAL})",
            "",
            "stop reasons: tool_use, end_turn, end_turn",
        ]
    )
